from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from channels_cleaner.api import sse
from channels_cleaner.events import CLOSED, EventBus

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from fastapi import Request


def request() -> Request:
    """What sse_response reads of a request: the network service, the scope, whether the client went away."""

    async def is_disconnected() -> bool:
        return False

    # No app context: nothing here may open the database, whose threads would outlive the test's loop
    network = SimpleNamespace(allows=lambda _: True, kicked=asyncio.Event())
    app = SimpleNamespace(state=SimpleNamespace(ctx=SimpleNamespace(network=network)))
    return cast("Request", SimpleNamespace(app=app, scope={}, is_disconnected=is_disconnected))


@contextlib.asynccontextmanager
async def stream(bus: EventBus) -> AsyncIterator[AsyncGenerator[Any]]:
    body = cast("AsyncGenerator[Any]", sse.sse_response(request(), bus, "topic", lambda: {"x": 1}).body_iterator)

    try:
        yield body

    finally:
        await body.aclose()


async def test_quiet_streams_ping_with_an_event_the_page_can_see(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sse, "PING_INTERVAL", 0.01)

    async with stream(EventBus()) as body:
        assert (await anext(body)).startswith("event: snapshot")
        # A comment line would never reach the page's EventSource
        assert await anext(body) == "event: ping\ndata: {}\n\n"


async def test_closing_the_bus_ends_every_open_stream() -> None:
    bus = EventBus()

    async with stream(bus) as body:
        await anext(body)

        bus.close()

        async with asyncio.timeout(1):
            with pytest.raises(StopAsyncIteration):
                await anext(body)

    # One opened while the app stops gets its snapshot and ends there
    async with stream(bus) as late:
        await anext(late)

        with pytest.raises(StopAsyncIteration):
            await anext(late)


def test_close_reaches_every_subscriber() -> None:
    bus = EventBus()

    with bus.subscribe("a") as first, bus.subscribe("b") as second:
        bus.close()

        assert (first.get_nowait().type, second.get_nowait().type) == (CLOSED, CLOSED)
