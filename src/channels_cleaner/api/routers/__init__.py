from fastapi import APIRouter

from channels_cleaner.api.models import ErrorResponse

from . import accounts, apply, auth, channels, decisions, health, network, results

# Every error has the same shape (api/errors.py); "default" also stands in for FastAPI's own 422 schema
router = APIRouter(prefix="/api", responses={"default": {"model": ErrorResponse, "description": "An error"}})

for module in (health, auth, accounts, channels, decisions, apply, results, network):
    router.include_router(module.router)

router.include_router(network.pairing_router)

__all__ = ("router",)
