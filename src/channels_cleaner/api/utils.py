"""OpenAPI descriptions of the answers that aren't JSON models."""

from typing import Any

from channels_cleaner.api import models

EVENT_STREAM: dict[int | str, dict[str, Any]] = {
    200: {"description": "Server-sent events: a snapshot first, then changes", "content": {"text/event-stream": {}}},
}

PICTURE: dict[int | str, dict[str, Any]] = {
    200: {"description": "The picture, cached by Telegram's file id", "content": {"image/*": {}}},
}

EXPORT: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The chats left, as a file to save",
        "model": list[models.ExportRow],
        "content": {"text/csv": {}},
    },
}

#: pictures are addressed with a version in the query, so a changed one is a new URL
IMMUTABLE = {"Cache-Control": "private, max-age=604800, immutable"}
