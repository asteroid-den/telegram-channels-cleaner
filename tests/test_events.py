from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from channels_cleaner.api import sse
from channels_cleaner.events import CLOSED, EventBus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request

    from channels_cleaner.context import AppContext


def request_for(ctx: AppContext) -> Request:
    """What sse_response reads of a request: the app's context, the scope, whether the client went away."""

    async def is_disconnected() -> bool:
        return False

    fake = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)), scope={}, is_disconnected=is_disconnected
    )
    return cast("Request", fake)


def stream(ctx: AppContext, bus: EventBus) -> AsyncIterator[Any]:
    response = sse.sse_response(request_for(ctx), bus, "topic", lambda: {"x": 1})
    return cast("AsyncIterator[Any]", response.body_iterator)


async def test_quiet_streams_ping_with_an_event_the_page_can_see(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse, "PING_INTERVAL", 0.01)
    body = stream(ctx, EventBus())

    assert (await anext(body)).startswith("event: snapshot")
    # A comment line would never reach the page's EventSource
    assert await anext(body) == "event: ping\ndata: {}\n\n"


async def test_closing_the_bus_ends_every_open_stream(ctx: AppContext) -> None:
    bus = EventBus()
    body = stream(ctx, bus)
    await anext(body)

    bus.close()

    async with asyncio.timeout(1):
        with pytest.raises(StopAsyncIteration):
            await anext(body)

    # One opened while the app stops gets its snapshot and ends there
    late = stream(ctx, bus)
    await anext(late)

    with pytest.raises(StopAsyncIteration):
        await anext(late)


def test_close_reaches_every_subscriber() -> None:
    bus = EventBus()

    with bus.subscribe("a") as first, bus.subscribe("b") as second:
        bus.close()

        assert (first.get_nowait().type, second.get_nowait().type) == (CLOSED, CLOSED)
