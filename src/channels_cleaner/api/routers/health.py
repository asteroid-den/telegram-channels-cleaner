from fastapi import APIRouter

from channels_cleaner import __version__
from channels_cleaner.api import errors, models
from channels_cleaner.api.dependencies import ContextDep

router = APIRouter(tags=["health"])


@router.get("/health", responses=errors.error_responses())
async def get_health(ctx: ContextDep) -> models.HealthResponse:
    return models.HealthResponse(version=__version__, mock=ctx.settings.mock)
