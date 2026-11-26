"""Keeps other websites and other devices out of the API.

Any page in the user's browser can reach localhost: a cross-site "simple" POST could start the apply job (CSRF); a
domain rebound to 127.0.0.1 could read everything. So every request must name a local host, and one that changes
something must come from the app's own page. A request that came in through the network listener (phone access)
must name the address that listener serves and show the cookie of a paired device; without one it gets only the page
itself and the pairing endpoints.
"""

import json
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from channels_cleaner.api import errors
from channels_cleaner.services import COOKIE, DEVICE_SCOPE, LAN_SCOPE

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Fetch metadata of a browser request from the app's own page, or typed into the address bar
OWN_PAGE = frozenset({"same-origin", "none"})


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, *, extra_hosts: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.hosts = LOCAL_HOSTS | extra_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        host = headers.get("host", "")
        lan = scope.get(LAN_SCOPE)

        if host != lan if lan else urlsplit(f"//{host}").hostname not in self.hosts:
            await refuse(send, errors.HostNotAllowed())
            return

        if scope["method"] not in SAFE_METHODS and not from_own_page(headers, host):
            await refuse(send, errors.CrossOriginRefused())
            return

        if lan:
            network = scope["app"].state.ctx.network
            device = network.device(cookie(headers, COOKIE))

            if device is not None:
                client = scope.get("client")
                await network.seen(device, client[0] if client else None)
                scope = {**scope, DEVICE_SCOPE: device.id}

            elif not open_to_strangers(scope["method"], scope["path"]):
                await refuse(send, errors.DeviceNotPaired())
                return

        await self.app(scope, receive, send)


#: what a device that isn't paired yet may ask for on the network listener; the routes check the rest
STRANGER_ROUTES = frozenset({("GET", "/api/health"), ("GET", "/api/pairing"), ("POST", "/api/pairing/claim")})


def open_to_strangers(method: str, path: str) -> bool:
    # The page itself and its scripts: the pairing screen is a page of the app. Nothing in them is private
    return (method, path) in STRANGER_ROUTES or (method in SAFE_METHODS and not path.startswith("/api/"))


def cookie(headers: dict[str, str], name: str) -> str | None:
    try:
        morsel = SimpleCookie(headers.get("cookie", "")).get(name)

    except CookieError:
        return None

    return morsel.value if morsel else None


def from_own_page(headers: dict[str, str], host: str) -> bool:
    # Browsers send both on every cross-origin request that changes something; a client without them (curl, the
    # tests) is not a page some site made the browser run
    if headers.get("sec-fetch-site", "same-origin") not in OWN_PAGE:
        return False

    origin = headers.get("origin")
    return origin is None or origin == f"http://{host}"


async def refuse(send: Send, error: errors.BaseError) -> None:
    body = json.dumps(error.body()).encode()
    await send(
        {
            "type": "http.response.start",
            "status": error.CODE,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
