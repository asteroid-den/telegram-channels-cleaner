from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from channels_cleaner.events import Event, EventBus
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

    done, pending = await asyncio.wait(waiters, timeout=PING_INTERVAL, return_when=asyncio.FIRST_COMPLETED)

    for waiter in pending:
        waiter.cancel()

    return getter.result() if getter in done else None


def sse_response(
    request: Request, bus: EventBus, topic: str, snapshot: Callable[[], dict[str, Any]]
) -> StreamingResponse:
    network = request.app.state.ctx.network
    # Only a device in the network can lose access while its stream is open
    lan = LAN_SCOPE in request.scope

    async def stream() -> AsyncIterator[str]:
        with bus.subscribe(topic) as queue:
            yield format_event("snapshot", snapshot())

            while True:
                # A device disconnected on the computer loses its open streams too
                if await request.is_disconnected() or not network.allows(request.scope):
                    return

                event = await next_event(queue, network.kicked if lan else None)

                if event is None:
                    if network.allows(request.scope):
                        yield ": ping\n\n"

                    continue

                yield format_event(event.type, event.data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
