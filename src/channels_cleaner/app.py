from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response

from channels_cleaner import __version__
from channels_cleaner.api import errors
from channels_cleaner.api.middlewares import LocalOnlyMiddleware
from channels_cleaner.api.routers import router
from channels_cleaner.config import Settings
from channels_cleaner.context import AppContext

STATIC_DIR = Path(__file__).parent / "static"
# Not in every system's mime table: served as octet-stream, the manifest of "Add to Home screen" would be refused
mimetypes.add_type("application/manifest+json", ".webmanifest")

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Channels Cleaner</title>
<body style="font-family:system-ui;padding:2rem;background:#111;color:#eee">
<h1>Frontend is not built</h1>
<p>Run <code>npm --prefix frontend ci && npm --prefix frontend run build</code>
and restart, or use the Vite dev server (<code>npm --prefix frontend run dev</code>).</p>"""


async def serve_spa(path: str) -> Response:
    if path.startswith("api/"):
        return errors.RouteNotFound().response()

    index = STATIC_DIR / "index.html"

    if not index.exists():
        return HTMLResponse(NOT_BUILT, status_code=503)

    candidate = (STATIC_DIR / path).resolve()

    if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)

    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    settings = settings or Settings()
    context = ctx or AppContext.create(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await context.startup()
        app.state.ctx = context

        try:
            yield

        finally:
            await context.shutdown()

    app = FastAPI(title="Channels Cleaner", version=__version__, lifespan=lifespan)
    # A host the server was told to listen on by name (not 0.0.0.0) is the user's choice too
    named = frozenset({settings.host}) - {"0.0.0.0", "::"}  # noqa: S104 - not a bind
    app.add_middleware(LocalOnlyMiddleware, extra_hosts=named)
    app.include_router(router)

    errors.install(app)

    app.add_api_route("/{path:path}", serve_spa, methods=["GET"], include_in_schema=False)
    # The network listener serves this same app, middlewares included
    context.network.app = app
    return app
