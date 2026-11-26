from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from channels_cleaner.api import errors, models, utils
from channels_cleaner.api.dependencies import ContextDep, DAODep

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", responses=errors.error_responses())
async def get_accounts(ctx: ContextDep, dao: DAODep) -> models.AccountsResponse:
    active = ctx.auth.state.user.id if ctx.auth.state.status == "authorized" and ctx.auth.state.user else None
    return models.AccountsResponse(
        items=[
            models.Account(
                id=account.id,
                first_name=account.first_name,
                last_name=account.last_name,
                username=account.username,
                avatar_url=avatar_url(account.id, ctx.channels.own_photo(account.id)),
                active=account.id == active,
                chats=await dao.count_channels(account.id),
                pending=await dao.count_pending(account.id),
            )
            for account in await dao.list_accounts()
        ]
    )


def avatar_url(account_id: int, photo: Path | None) -> str | None:
    # The file keeps its name when the photo changes: its time tells the versions apart
    return f"/api/accounts/{account_id}/avatar?v={photo.stat().st_mtime_ns}" if photo else None


@router.get(
    "/{account_id}/avatar",
    response_class=FileResponse,
    responses={**errors.error_responses(errors.AvatarNotFound), **utils.PICTURE},
)
async def get_account_avatar(account_id: int, ctx: ContextDep) -> FileResponse:
    photo = ctx.channels.own_photo(account_id)

    if photo is None:
        raise errors.AvatarNotFound(account_id=account_id)

    return FileResponse(photo, headers=utils.IMMUTABLE)


@router.post(
    "/{account_id}/activate",
    responses=errors.error_responses(errors.AccountNotFound, errors.ApplyJobRunning, errors.TelegramError),
)
async def post_activate_account(account_id: int, ctx: ContextDep) -> models.AuthStateResponse:
    await ctx.switch_account(account_id)
    return models.AuthStateResponse.model_validate(ctx.auth.state)


@router.post("/add", responses=errors.error_responses(errors.ApplyJobRunning, errors.TelegramError))
async def post_add_account(ctx: ContextDep) -> models.AuthStateResponse:
    """Connects a new session: the login screen then logs in another account, the others stay."""
    await ctx.add_account()
    return models.AuthStateResponse.model_validate(ctx.auth.state)
