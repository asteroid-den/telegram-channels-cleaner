from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from channels_cleaner.config import Settings
from channels_cleaner.context import AppContext
from channels_cleaner.database import utc_now
from channels_cleaner.services import DEVICE_SCOPE, LAN_SCOPE, network
from channels_cleaner.services.network import device_name, mark_lan
from tests.conftest import check_error_is_declared, get_json

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.1 Mobile/15E148 Safari/604.1"
)
PIXEL = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile "
    "Safari/537.36"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        mock=True,
        mock_channels=5,
        mock_supergroups=0,
        port=free_port(),
        _env_file=None,  # pyright: ignore[reportCallIssue] - pydantic-settings init option, not a field
    )


@pytest.fixture(autouse=True)
def home_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # The listener goes up on loopback: a real socket, without depending on the machine's network
    monkeypatch.setattr(network, "lan_address", lambda: "127.0.0.1")


@dataclass
class Setup:
    ctx: AppContext
    app: FastAPI
    computer: httpx.AsyncClient

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.ctx.settings.port}"

    def phone(self, user_agent: str = IPHONE) -> httpx.AsyncClient:
        """A browser in the network: its requests come in through the network listener."""

        async def declared_errors_only(response: httpx.Response) -> None:
            await response.aread()
            check_error_is_declared(self.app, response)

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mark_lan(self.app, self.address), client=("192.168.1.41", 50000)),
            base_url=f"http://{self.address}",
            headers={"User-Agent": user_agent},
            event_hooks={"response": [declared_errors_only]},
        )


@pytest.fixture
async def setup(ctx: AppContext, client: httpx.AsyncClient) -> Setup:
    app = ctx.network.app
    assert isinstance(app, FastAPI)
    return Setup(ctx, app, client)


async def turn_on(computer: httpx.AsyncClient) -> dict[str, object]:
    r = await computer.put("/api/network", json={"enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


async def pair(setup: Setup, phone: httpx.AsyncClient) -> str:
    """The whole pairing: the QR on the computer, the link on the phone, the yes on the computer. Returns the code."""
    pairing = (await setup.computer.post("/api/network/pairing")).json()["pairing"]
    token = pairing["url"].rsplit("/", 1)[1]

    r = await phone.post("/api/pairing/claim", json={"token": token})

    assert r.status_code == 200, r.text
    assert r.json()["code"] == pairing["code"]
    assert (await setup.computer.post("/api/network/pairing/approve")).status_code == 200
    return pairing["code"]


async def test_the_toggle_starts_and_stops_listening_in_the_network(setup: Setup) -> None:
    state = await turn_on(setup.computer)

    assert (state["enabled"], state["url"]) == (True, f"http://{setup.address}")

    # A real socket, not the test transport
    async with httpx.AsyncClient(base_url=state["url"]) as outside:  # pyright: ignore[reportArgumentType]
        assert (await outside.get("/api/health")).status_code == 200
        r = await outside.get("/api/auth/state")
        assert (r.status_code, r.json()["type"]) == (401, "device_not_paired")

        state = (await setup.computer.put("/api/network", json={"enabled": False})).json()
        assert (state["enabled"], state["url"]) == (False, None)

        with pytest.raises(httpx.ConnectError):
            await outside.get("/api/health")


async def test_a_phone_is_let_in_only_after_the_yes_on_the_computer(setup: Setup) -> None:
    await turn_on(setup.computer)
    pairing = (await setup.computer.post("/api/network/pairing")).json()["pairing"]
    assert pairing["url"].startswith(f"http://{setup.address}/pair/")
    assert len(pairing["code"]) == 4

    async with setup.phone() as phone:
        assert (await phone.get("/api/auth/state")).status_code == 401
        # The page itself loads for anyone: it is the pairing screen
        assert (await phone.get("/pair/x")).status_code in {200, 503}

        r = await phone.post("/api/pairing/claim", json={"token": pairing["url"].rsplit("/", 1)[1]})

        assert r.json() == {"ok": True, "status": "waiting", "code": pairing["code"], "computer": socket.gethostname()}
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        # Holding the cookie is not enough yet
        assert (await phone.get("/api/auth/state")).status_code == 401
        assert (await get_json(phone, "/api/pairing"))["status"] == "waiting"
        request = (await get_json(setup.computer, "/api/network"))["pairing"]["request"]
        assert request == {"name": "iPhone · Safari", "ip": "192.168.1.41"}

        assert (await setup.computer.post("/api/network/pairing/approve")).status_code == 200

        assert (await get_json(phone, "/api/pairing"))["status"] == "paired"
        assert (await phone.get("/api/auth/state")).status_code == 200

    state = await get_json(setup.computer, "/api/network")
    assert state["pairing"] is None
    assert [(d["name"], d["last_ip"]) for d in state["devices"]] == [("iPhone · Safari", "192.168.1.41")]


async def test_a_link_works_once_and_not_for_long(setup: Setup) -> None:
    await turn_on(setup.computer)
    pairing = (await setup.computer.post("/api/network/pairing")).json()["pairing"]
    token = pairing["url"].rsplit("/", 1)[1]

    async with setup.phone() as phone, setup.phone(PIXEL) as other:
        r = await other.post("/api/pairing/claim", json={"token": "a" + token})
        assert (r.status_code, r.json()["type"]) == (404, "pairing_not_found")

        assert (await phone.post("/api/pairing/claim", json={"token": token})).status_code == 200

        # Whoever else caught the QR comes second: the one waiting is the user's to approve or not
        r = await other.post("/api/pairing/claim", json={"token": token})
        assert (r.status_code, r.json()["type"]) == (409, "pairing_taken")

    assert (await setup.computer.post("/api/network/pairing")).status_code == 200
    pairing = setup.ctx.network.pairing
    assert pairing is not None
    pairing.expires_at = utc_now() - timedelta(seconds=1)

    async with setup.phone() as phone:
        r = await phone.post("/api/pairing/claim", json={"token": pairing.token})
        assert (r.status_code, r.json()["type"]) == (404, "pairing_not_found")

    assert (await get_json(setup.computer, "/api/network"))["pairing"] is None


async def test_a_rejected_phone_stays_out(setup: Setup) -> None:
    await turn_on(setup.computer)
    pairing = (await setup.computer.post("/api/network/pairing")).json()["pairing"]

    async with setup.phone() as phone:
        await phone.post("/api/pairing/claim", json={"token": pairing["url"].rsplit("/", 1)[1]})

        assert (await setup.computer.post("/api/network/pairing/reject")).status_code == 200

        r = await phone.get("/api/pairing")
        assert (r.status_code, r.json()["type"]) == (401, "device_not_paired")
        assert (await phone.get("/api/auth/state")).status_code == 401

    assert (await get_json(setup.computer, "/api/network"))["devices"] == []


async def test_pairing_is_managed_on_the_computer_only(setup: Setup) -> None:
    await turn_on(setup.computer)

    async with setup.phone() as phone:
        await pair(setup, phone)

        for method, url in (("GET", "/api/network"), ("POST", "/api/network/pairing"), ("PUT", "/api/network")):
            r = await phone.request(method, url, json={"enabled": False}, headers={"Origin": f"http://{setup.address}"})
            assert (r.status_code, r.json()["type"]) == (403, "computer_only"), url


async def test_pairing_needs_the_network_on(setup: Setup) -> None:
    r = await setup.computer.post("/api/network/pairing")

    assert (r.status_code, r.json()["type"]) == (409, "network_access_off")


async def test_a_disconnected_device_is_out_at_once(setup: Setup) -> None:
    await turn_on(setup.computer)

    async with setup.phone() as phone:
        await pair(setup, phone)
        device = (await get_json(setup.computer, "/api/network"))["devices"][0]

        r = await setup.computer.patch(f"/api/network/devices/{device['id']}", json={"name": "  Kitchen  "})
        assert r.json()["devices"][0]["name"] == "Kitchen"
        r = await setup.computer.patch(f"/api/network/devices/{device['id']}", json={"name": "   "})
        assert r.status_code == 422

        streaming = {LAN_SCOPE: setup.address, DEVICE_SCOPE: device["id"]}
        assert setup.ctx.network.allows(streaming)

        assert (await setup.computer.delete(f"/api/network/devices/{device['id']}")).status_code == 200

        assert (await phone.get("/api/auth/state")).status_code == 401
        # Its open event streams end at the next ping
        assert not setup.ctx.network.allows(streaming)
        r = await setup.computer.delete(f"/api/network/devices/{device['id']}")
        assert (r.status_code, r.json()["type"]) == (404, "device_not_found")


async def test_the_network_listener_checks_host_and_origin(setup: Setup) -> None:
    await turn_on(setup.computer)

    async with setup.phone() as phone:
        await pair(setup, phone)

        # Only the address it serves: not a rebound domain, not "localhost" from another machine
        for host in ("evil.example", f"localhost:{setup.ctx.settings.port}"):
            r = await phone.get("/api/auth/state", headers={"Host": host})
            assert (r.status_code, r.json()["type"]) == (403, "host_not_allowed")

        r = await phone.post("/api/apply", headers={"Origin": "https://evil.example"})
        assert (r.status_code, r.json()["type"]) == (403, "cross_origin_refused")


async def test_paired_devices_and_the_toggle_outlive_a_restart(setup: Setup) -> None:
    await turn_on(setup.computer)

    async with setup.phone() as phone:
        await pair(setup, phone)

        await setup.ctx.network.stop()
        setup.ctx.network.devices.clear()
        await setup.ctx.network.startup()

        assert setup.ctx.network.enabled
        assert (await phone.get("/api/auth/state")).status_code == 200


async def test_the_toggle_is_off_limits_when_the_app_already_listens_everywhere(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Started with --host 0.0.0.0 (or in Docker): the network service reads the setting each time it is asked
    monkeypatch.setattr(setup.ctx.settings, "host", "0.0.0.0")  # noqa: S104 - not a bind

    state = await get_json(setup.computer, "/api/network")
    r = await setup.computer.put("/api/network", json={"enabled": True})

    assert (state["available"], state["unavailable_reason"]) == (False, "custom_host")
    assert (r.status_code, r.json()["type"], r.json()["reason"]) == (409, "network_unavailable", "custom_host")
    assert not setup.ctx.network.enabled


@pytest.mark.parametrize(
    ("user_agent", "name"),
    [
        (IPHONE, "iPhone · Safari"),
        (PIXEL, "Pixel 8 · Chrome"),
        (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36",
            "Android · Chrome",
        ),
        ("Mozilla/5.0 (Android 14; Mobile; rv:133.0) Gecko/133.0 Firefox/133.0", "Android · Firefox"),
        ("curl/8.5.0", "Device"),
    ],
)
def test_devices_are_named_after_their_browser(user_agent: str, name: str) -> None:
    assert device_name(user_agent) == name
