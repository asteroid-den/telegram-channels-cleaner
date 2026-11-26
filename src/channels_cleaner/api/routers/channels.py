from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse

from channels_cleaner.api import errors, models, utils
from channels_cleaner.api.dependencies import AccountIdDep, ContextDep, DAODep
from channels_cleaner.api.sse import sse_response
from channels_cleaner.enums import ArchiveFilter, ChatKind, RoleFilter, SortMode
from channels_cleaner.services import SYNC_TOPIC, deck

router = APIRouter(prefix="/channels", tags=["channels"])

FROM_TELEGRAM = (errors.NotAuthorized, errors.ChannelNotFound, errors.FloodWait, errors.TelegramError)


@router.post("/sync", responses=errors.error_responses(errors.NotAuthorized))
async def post_sync(ctx: ContextDep, account_id: AccountIdDep) -> models.SyncStateResponse:
    ctx.sync.start(account_id)
    return models.SyncStateResponse.model_validate(ctx.sync.state)


@router.get(
    "/sync/events", response_class=StreamingResponse, responses={**errors.error_responses(), **utils.EVENT_STREAM}
)
async def get_sync_events(request: Request, ctx: ContextDep) -> StreamingResponse:
    return sse_response(request, ctx.bus, SYNC_TOPIC, ctx.sync.state.snapshot)


@router.get("", responses=errors.error_responses(errors.NotAuthorized))
async def get_channels(  # noqa: PLR0913
    ctx: ContextDep,
    dao: DAODep,
    account_id: AccountIdDep,
    *,
    kind: ChatKind = ChatKind.CHANNEL,
    role: RoleFilter = RoleFilter.MEMBER,
    archive: ArchiveFilter | None = None,
    sort: SortMode = SortMode.DEAD,
    reverse: bool = False,
    state: Literal["undecided", "all"] = "undecided",
) -> models.DeckResponse:
    archive = await deck.archive_filter(dao, account_id, archive)
    channels = await dao.list_channels(
        account_id,
        kind=kind,
        role=role,
        archive=archive,
        sort=sort,
        reverse=reverse,
        undecided_only=state == "undecided",
    )
    return models.DeckResponse(
        items=[models.Channel.from_channel(channel) for channel in channels],
        counts=await deck.counts(dao, account_id, kind, role, archive),
        sync=models.SyncState.model_validate(ctx.sync.state),
    )


@router.get("/{channel_id}/full", responses=errors.error_responses(*FROM_TELEGRAM))
async def get_channel_full(channel_id: int, ctx: ContextDep, account_id: AccountIdDep) -> models.ChannelResponse:
    return models.ChannelResponse.from_channel(await ctx.channels.get_full(account_id, channel_id))


@router.get(
    "/{channel_id}/avatar",
    response_class=FileResponse,
    responses={**errors.error_responses(*FROM_TELEGRAM, errors.PictureNotFound), **utils.PICTURE},
)
async def get_channel_avatar(channel_id: int, ctx: ContextDep, account_id: AccountIdDep) -> FileResponse:
    path = await ctx.channels.avatar(account_id, channel_id)

    if path is None:
        raise errors.PictureNotFound(channel_id=channel_id)

    return FileResponse(path, headers=utils.IMMUTABLE)


@router.get(
    "/{channel_id}/thumb",
    response_class=FileResponse,
    responses={**errors.error_responses(*FROM_TELEGRAM, errors.PictureNotFound), **utils.PICTURE},
)
async def get_channel_thumb(channel_id: int, ctx: ContextDep, account_id: AccountIdDep) -> FileResponse:
    path = await ctx.channels.post_thumb(account_id, channel_id)

    if path is None:
        raise errors.PictureNotFound(channel_id=channel_id)

    return FileResponse(path, headers=utils.IMMUTABLE)
