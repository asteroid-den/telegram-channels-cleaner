from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from typing import Any

import uvicorn
from pydantic import ValidationError

from channels_cleaner import logs
from channels_cleaner.app import STATIC_DIR, create_app
from channels_cleaner.browser import open_url
from channels_cleaner.config import Settings


def port_in_use(host: str, port: int) -> bool:
    """Try binding like uvicorn does (SO_REUSEADDR), so TIME_WAIT leftovers don't count."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET

    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((host, port))

        except OSError as exc:
            return exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1))

    return False


def running_instance(url: str) -> dict[str, object] | None:
    try:
        # Always our own http:// URL, never user input
        with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:  # noqa: S310
            data = json.loads(response.read())

    except (OSError, ValueError):
        return None

    return data if isinstance(data, dict) and data.get("ok") else None


def port_busy_message(host: str, port: int, url: str) -> str:
    instance = running_instance(url)

    if instance is not None:
        mode = "mock mode" if instance.get("mock") else "real account"
        first = f"Channels Cleaner ({mode}) is already running at {url}."
        hint = "Open it in the browser, or stop that process first (Ctrl+C in its terminal)."

    else:
        first = f"Port {port} on {host} is already taken by another program."
        hint = "Stop that program, or pick another port:"

    return f"✗ {first}\n  {hint}\n  uv run telegram-channels-cleaner --port {port + 1}"


def open_when_ready(server: uvicorn.Server, url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if server.started:
            open_url(url)
            return

        if server.should_exit:
            return

        time.sleep(0.1)


def settings_error_message(error: ValidationError) -> str:
    lines = ["Invalid settings:"]

    for item in error.errors():
        name = "_".join(str(part) for part in item["loc"]).upper()
        lines.append(f"  CC_{name}: {item['msg']}" if name else f"  {item['msg']}")

    return "\n".join(lines)


def settings_from_args(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}

    if args.host:
        overrides["host"] = args.host

    if args.port:
        overrides["port"] = args.port

    if args.mock:
        overrides["mock"] = True

    try:
        settings = Settings(**overrides)

    except ValidationError as e:
        print(settings_error_message(e), file=sys.stderr)
        sys.exit(2)

    return settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="telegram-channels-cleaner", description=__doc__)
    parser.add_argument("--host", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port (default 8765)")
    parser.add_argument("--mock", action="store_true", help="use fake Telegram data")
    # Leaving a chat you own is a choice on its card now; the old switch is still taken, and ignored
    parser.add_argument("--allow-owner-leave", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--dev", action="store_true", help="API only; open the Vite dev server instead")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    settings = settings_from_args(args)

    settings.ensure_dirs()
    log_file = logs.setup(settings.log_dir, verbose=args.verbose)

    # In a container the server listens on all interfaces; the browser still uses localhost.
    shown_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host  # noqa: S104 - not a bind
    api_url = f"http://{shown_host}:{settings.port}"

    if port_in_use(settings.host, settings.port):
        print(port_busy_message(settings.host, settings.port, api_url), file=sys.stderr)
        sys.exit(1)

    url = "http://localhost:5173" if args.dev else api_url

    if not args.dev and not (STATIC_DIR / "index.html").exists():
        print("⚠  Frontend is not built yet. Run:\n   npm --prefix frontend ci && npm --prefix frontend run build\n")

    mode = " (mock mode)" if settings.mock else ""
    print(f"Channels Cleaner{mode} → {url}  (Ctrl+C to stop)")
    print(f"Data: {settings.data_dir.resolve()}")
    print(f"Log:  {log_file.resolve()}")

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            log_level="info" if args.verbose else "warning",
            # Its records go through ours: to the console and the log file, crashes of a request included
            log_config=None,
        )
    )

    if not args.no_browser and not os.environ.get("CC_NO_BROWSER"):
        threading.Thread(target=open_when_ready, args=(server, url), daemon=True).start()

    server.run()

    if not server.started:  # lost a race for the port after our check
        sys.exit(1)


if __name__ == "__main__":
    main()
