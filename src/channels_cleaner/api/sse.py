from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from channels_cleaner.events import CLOSED, Event, EventBus
from channels_cleaner.services import LAN_SCOPE

#: also how a phone tells the computer went away: no ping for a few seconds
PING_INTERVAL = 3.0


def format_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


async def next_event(queue: asyncio.Queue[Event], kicked: asyncio.Event | None) -> Event | None:
    """The next event, or None after a ping interval of quiet or once devices are kicked out."""
    getter = asyncio.ensure_future(queue.get())
    waiters: set[asyncio.Future[Any]] = {getter}

    if kicked is not None:
        waiters.add(asyncio.ensure_future(kicked.wait()))

    try:
        await asyncio.wait(waiters, timeout=PING_INTERVAL, return_when=asyncio.FIRST_COMPLETED)

    finally:
        # Also when the stream itself is cancelled here (a tab closed, a phone gone): a waiter left pending outlives its
        # queue, and the garbage collector logs "Task was destroyed but it is pending!" for it
        for waiter in waiters:
            waiter.cancel()

        await asyncio.gather(*waiters, return_exceptions=True)

    # The getter got its event in time, or just as the wait ended: then the cancel came too late, and it still counts
    return None if getter.cancelled() else getter.result()


def sse_response(
    request: Request, bus: EventBus, topic: str, snapshot: Callable[[], dict[str, Any]]
) -> StreamingResponse:
    network = request.app.state.ctx.network
    # Only a device in the network can lose access while its stream is open
    lan = LAN_SCOPE in request.scope

    async def stream() -> AsyncIterator[str]:
        with bus.subscribe(topic) as queue:
            yield format_event("snapshot", snapshot())

            if bus.closed:
                return

            while True:
                if await request.is_disconnected():
                    return

                # A device disconnected on the computer loses its open streams too. It hears why first, and goes to
                # the pairing screen at once instead of after the silence it would otherwise have to notice
                if not network.allows(request.scope):
                    if network.revoked(request.scope):
                        yield format_event("revoked", {})

                    return

                event = await next_event(queue, network.kicked if lan else None)

                if event is None:
                    # An event, not an SSE comment: the page sees it, and tells a quiet stream from a dead one
                    if network.allows(request.scope):
                        yield format_event("ping", {})

                    continue

                # The app is stopping
                if event.type == CLOSED:
                    return

                yield format_event(event.type, event.data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
