"""Phone access: a second listener in the local network, pairing by QR, and the devices that were let in.

The app's own listener stays on 127.0.0.1 and is trusted as before (the guard checks Host and Origin). The one in
the network is started only when the user turns it on, serves the same app, and marks its requests: the guard lets
them through only with the cookie of a paired device. Pairing: the computer shows a QR with a one-time link and a
4-digit code; the phone that opens the link gets a cookie at once, but it counts only after the user approves that
phone on the computer, seeing the same code on both screens. So whoever else catches the QR is turned away there.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import ipaddress
import logging
import re
import secrets
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from channels_cleaner.api.errors import (
    DeviceNotFound,
    NetworkAccessOff,
    NetworkUnavailable,
    PairingNotFound,
    PairingTaken,
)
from channels_cleaner.config import Settings
from channels_cleaner.database import DAO, DatabaseManager, utc_now
from channels_cleaner.events import EventBus

log = logging.getLogger(__name__)

NETWORK_TOPIC = "network"
#: the settings row of the app itself, not of an account (Telegram ids are never 0)
APP_WIDE = 0
ENABLED_SETTING = "network_enabled"
#: the scope key the network listener sets: the address it serves, as the Host header names it
LAN_SCOPE = "channels_cleaner.lan"
#: the scope key the guard sets for a request of a paired device: its id
DEVICE_SCOPE = "channels_cleaner.device"
COOKIE = "cc_device"
#: the longest a browser keeps a cookie (Chrome caps it at 400 days)
COOKIE_MAX_AGE = 400 * 24 * 3600
PAIRING_TTL = timedelta(minutes=2)
# The link's secret is short enough to type in on a phone: lowercase, no look-alikes (0/o, 1/l). It lives two minutes,
# takes one claim, and the device it lets in still needs the user's yes on the computer.
TOKEN_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # noqa: S105 - characters, not a secret
TOKEN_LENGTH = 8

#: how often a device's last visit is written down: every request would be a write
SEEN_EVERY = timedelta(minutes=1)
NAME_LENGTH = 64
#: an address of TEST-NET-1: connecting a UDP socket to it sends nothing, it only picks the outgoing interface
ROUTE_PROBE = ("192.0.2.1", 9)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lan_address() -> str | None:
    """This computer's address in the local network: the one its traffic goes out from."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(ROUTE_PROBE)

        except OSError:
            return None

        address: str = probe.getsockname()[0]

    ip = ipaddress.ip_address(address)
    return None if ip.is_loopback or ip.is_unspecified else address


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True

    try:
        return ipaddress.ip_address(host).is_loopback

    except ValueError:
        return False


def in_container() -> bool:
    return Path("/.dockerenv").exists()


BROWSERS = (("Edg/", "Edge"), ("SamsungBrowser", "Samsung Internet"), ("Firefox", "Firefox"), ("FxiOS", "Firefox"),
            ("CriOS", "Chrome"), ("Chrome", "Chrome"), ("Safari", "Safari"))  # fmt: skip
SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Macintosh", "Mac"),
           ("Windows", "Windows"), ("Linux", "Linux"))  # fmt: skip


def device_name(user_agent: str) -> str:
    """ "iPhone · Safari", "Pixel 8 · Chrome": what the user can tell their devices apart by; renamed at will."""
    system = next((name for marker, name in SYSTEMS if marker in user_agent), None)

    # Android browsers that still say the model: "Android 14; Pixel 8)" (Chrome now sends a bare "K")
    if system == "Android" and (model := re.search(r"Android [\d.]+; ([^;)]+?)(?: Build/[^;)]*)?\)", user_agent)):
        system = model.group(1).strip() if len(model.group(1).strip()) > 1 else system

    browser = next((name for marker, name in BROWSERS if marker in user_agent), None)
    return " · ".join(part for part in (system, browser) if part) or "Device"


@dataclass(slots=True)
class PairedDevice:
    id: int
    name: str
    token_hash: str
    created_at: datetime
    last_seen_at: datetime
    last_ip: str | None
    #: when last_seen_at was last written down
    saved_at: datetime


@dataclass(slots=True)
class PairingRequest:
    """The device that opened the link and waits for the user's yes on the computer."""

    name: str
    user_agent: str
    ip: str | None
    token_hash: str


@dataclass(slots=True)
class Pairing:
    token: str
    code: str
    expires_at: datetime
    request: PairingRequest | None = None

    @property
    def expired(self) -> bool:
        return utc_now() >= self.expires_at


class LanServer(uvicorn.Server):
    """The network listener: a uvicorn server in the app's own loop, started and stopped by the user."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        # Ctrl+C belongs to the app's own server, which stops this one on its way out
        yield


def mark_lan(app: ASGIApp, address: str) -> ASGIApp:
    async def marked(scope: Scope, receive: Receive, send: Send) -> None:
        await app({**scope, LAN_SCOPE: address}, receive, send)

    return marked


class NetworkService:
    def __init__(self, database: DatabaseManager, bus: EventBus, settings: Settings) -> None:
        self.database = database
        self.bus = bus
        self.settings = settings
        #: the app to serve; app.py hands it over (the context is made before the app)
        self.app: ASGIApp | None = None
        self.server: LanServer | None = None
        self.server_task: asyncio.Task[None] | None = None
        self.sock: socket.socket | None = None
        self.address: str | None = None
        self.error: str | None = None
        self.pairing: Pairing | None = None
        self.devices: dict[str, PairedDevice] = {}
        #: set while the listener stops: its event streams end instead of holding the stop up
        self.closing = False
        #: wakes the event streams of devices when some of them lose access (see sse.py)
        self.kicked = asyncio.Event()

    @property
    def unavailable(self) -> str | None:
        """Why the toggle can't work here: the app already listens beyond this computer, by its settings."""
        if is_loopback(self.settings.host):
            return None

        return "container" if in_container() else "custom_host"

    @property
    def enabled(self) -> bool:
        return self.server is not None

    @property
    def url(self) -> str | None:
        return f"http://{self.address}" if self.address else None

    def qr_link(self, token: str | None = None) -> str | None:
        """What a QR code says. Phone cameras open a link only when it has a domain, so it goes through the pairing
        page, with the address (and the pairing token) after `#`. Without a token: the app, for a paired phone."""
        if not self.address:
            return None

        path = f"/{token}" if token else ""

        if self.settings.pairing_page:
            return f"{self.settings.pairing_page}#{self.address}{path}"

        return f"{self.url}/pair/{token}" if token else self.url

    def snapshot(self) -> dict[str, Any]:
        pairing = self.pairing if self.pairing and not self.pairing.expired else None
        return {
            "available": self.unavailable is None,
            "unavailable_reason": self.unavailable,
            "enabled": self.enabled,
            "url": self.url,
            "open_qr": self.qr_link(),
            "error": self.error,
            "pairing": pairing
            and {
                "url": f"{self.url}/pair/{pairing.token}",
                "qr": self.qr_link(pairing.token),
                "code": pairing.code,
                "expires_at": pairing.expires_at.isoformat(),
                "request": pairing.request and {"name": pairing.request.name, "ip": pairing.request.ip},
            },
            "devices": [
                {
                    "id": device.id,
                    "name": device.name,
                    "created_at": device.created_at.isoformat(),
                    "last_seen_at": device.last_seen_at.isoformat(),
                    "last_ip": device.last_ip,
                }
                for device in sorted(self.devices.values(), key=lambda d: (d.last_seen_at, d.id), reverse=True)
            ],
        }

    def publish(self) -> None:
        self.bus.publish(NETWORK_TOPIC, "state", **self.snapshot())

    async def startup(self) -> None:
        async with self.database.session() as session:
            dao = DAO(session)
            enabled = await dao.get_setting(APP_WIDE, ENABLED_SETTING)
            rows = await dao.list_devices()

        self.devices = {
            row.token_hash: PairedDevice(
                id=row.id,
                name=row.name,
                token_hash=row.token_hash,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                last_ip=row.last_ip,
                saved_at=row.last_seen_at,
            )
            for row in rows
        }

        if not enabled or self.unavailable:
            return

        # Turned on last time: the phones expect to find the app again. The address may have changed
        try:
            await self.listen()

        except NetworkUnavailable as exc:
            log.warning("Could not let devices in from the network: %s", exc.reason)
            self.error = exc.reason

    async def enable(self) -> None:
        if reason := self.unavailable:
            raise NetworkUnavailable(reason=reason)

        if not self.enabled:
            try:
                await self.listen()

            except NetworkUnavailable as exc:
                self.error = exc.reason
                self.publish()
                raise

        await self.save_enabled(value=True)
        self.publish()

    async def disable(self) -> None:
        await self.stop()
        self.pairing = None
        self.error = None
        await self.save_enabled(value=False)
        self.publish()

    async def save_enabled(self, *, value: bool) -> None:
        async with self.database.session() as session:
            dao = DAO(session)
            await dao.set_setting(APP_WIDE, ENABLED_SETTING, value)
            await dao.commit()

    async def listen(self) -> None:
        if self.app is None:
            msg = "app.py hands the app over before the context starts"
            raise RuntimeError(msg)

        address = lan_address()

        if address is None:
            raise NetworkUnavailable(reason="no_network")

        try:
            sock = socket.create_server((address, self.settings.port))

        except OSError as exc:
            reason = "address_in_use" if exc.errno == errno.EADDRINUSE else (exc.strerror or str(exc))
            raise NetworkUnavailable(reason=reason) from exc

        served = f"{address}:{self.settings.port}"
        config = uvicorn.Config(
            mark_lan(self.app, served),
            lifespan="off",
            log_config=None,
            log_level="warning",
            # Open event streams would hold the stop for good
            timeout_graceful_shutdown=1,
        )
        self.server = LanServer(config)
        self.server_task = asyncio.create_task(self.server.serve(sockets=[sock]), name="network listener")
        self.sock = sock
        self.address = served
        self.error = None
        log.info("Letting paired devices in at http://%s", served)

    async def stop(self) -> None:
        if self.server is None or self.server_task is None:
            return

        self.closing = True
        self.kick()
        self.server.should_exit = True

        try:
            await self.server_task

        finally:
            if self.sock is not None:
                self.sock.close()

            self.server = self.server_task = self.sock = None
            self.address = None
            self.closing = False
            log.info("Stopped letting devices in from the network")

    def start_pairing(self) -> None:
        if not self.enabled:
            raise NetworkAccessOff

        self.pairing = Pairing(
            token="".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH)),
            code=f"{secrets.randbelow(10_000):04d}",
            expires_at=utc_now() + PAIRING_TTL,
        )
        self.publish()

    def cancel_pairing(self) -> None:
        self.pairing = None
        self.publish()

    def live_pairing(self) -> Pairing:
        if self.pairing is None or self.pairing.expired:
            raise PairingNotFound

        return self.pairing

    def claim(self, token: str, user_agent: str, ip: str | None) -> tuple[str, str]:
        """The phone opened the link: it gets its cookie now, valid once the user approves it. Returns both."""
        pairing = self.live_pairing()

        if not secrets.compare_digest(token, pairing.token):
            raise PairingNotFound

        if pairing.request is not None:
            raise PairingTaken

        cookie = secrets.token_urlsafe(32)
        pairing.request = PairingRequest(
            name=device_name(user_agent)[:NAME_LENGTH],
            user_agent=user_agent,
            ip=ip,
            token_hash=token_hash(cookie),
        )
        # Time to walk over to the computer and approve it
        pairing.expires_at = max(pairing.expires_at, utc_now() + PAIRING_TTL)
        self.publish()
        return cookie, pairing.code

    def waiting(self, token: str | None) -> Pairing | None:
        """The pairing this cookie waits on, if it does."""
        pairing = self.pairing

        if token is None or pairing is None or pairing.expired or pairing.request is None:
            return None

        return pairing if secrets.compare_digest(pairing.request.token_hash, token_hash(token)) else None

    async def approve(self) -> None:
        pairing = self.live_pairing()
        request = pairing.request

        if request is None:
            raise PairingNotFound

        now = utc_now()

        async with self.database.session() as session:
            dao = DAO(session)
            device = await dao.add_device(request.name, request.user_agent, request.token_hash, request.ip, now)
            await dao.commit()

        self.devices[request.token_hash] = PairedDevice(
            id=device.id,
            name=request.name,
            token_hash=request.token_hash,
            created_at=now,
            last_seen_at=now,
            last_ip=request.ip,
            saved_at=now,
        )
        self.pairing = None
        log.info("Paired a device: %s", request.name)
        self.publish()

    def reject(self) -> None:
        pairing = self.live_pairing()

        if pairing.request is None:
            raise PairingNotFound

        # The link is spent either way: the computer shows a new QR when asked
        self.pairing = None
        self.publish()

    def device(self, token: str | None) -> PairedDevice | None:
        return self.devices.get(token_hash(token)) if token else None

    def device_by_id(self, device_id: int) -> PairedDevice:
        found = next((device for device in self.devices.values() if device.id == device_id), None)

        if found is None:
            raise DeviceNotFound(device_id=device_id)

        return found

    def allows(self, scope: Scope) -> bool:
        """Whether the request may go on: its device may have been disconnected since it came in."""
        device_id = scope.get(DEVICE_SCOPE)

        if LAN_SCOPE not in scope:
            return True

        return self.enabled and not self.closing and any(device.id == device_id for device in self.devices.values())

    def kick(self) -> None:
        self.kicked.set()
        self.kicked = asyncio.Event()

    async def seen(self, device: PairedDevice, ip: str | None) -> None:
        now = utc_now()
        device.last_seen_at = now
        device.last_ip = ip

        if now - device.saved_at < SEEN_EVERY:
            return

        device.saved_at = now

        async with self.database.session() as session:
            dao = DAO(session)
            await dao.touch_device(device.id, ip, now)
            await dao.commit()

    async def rename(self, device_id: int, name: str) -> None:
        device = self.device_by_id(device_id)

        async with self.database.session() as session:
            dao = DAO(session)
            await dao.rename_device(device_id, name)
            await dao.commit()

        device.name = name
        self.publish()

    async def forget(self, device_id: int) -> None:
        device = self.device_by_id(device_id)

        async with self.database.session() as session:
            dao = DAO(session)
            await dao.delete_device(device_id)
            await dao.commit()

        del self.devices[device.token_hash]
        self.kick()
        log.info("Disconnected a device: %s", device.name)
        self.publish()
