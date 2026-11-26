from fastapi import APIRouter

from channels_cleaner.api import errors, models
from channels_cleaner.api.dependencies import AccountIdDep, ContextDep, DAODep
from channels_cleaner.database import DAO, utc_now
from channels_cleaner.database import models as db_models
from channels_cleaner.database import utils as db_utils
from channels_cleaner.enums import ArchiveFilter, ChatKind, DecisionStatus, RoleFilter
from channels_cleaner.services import decisions, deck

router = APIRouter(prefix="/decisions", tags=["decisions"])


async def get_chat(dao: DAO, account_id: int, channel_id: int) -> db_models.Channel:
    channel = await dao.get_channel(account_id, channel_id)

    if channel is None:
        raise errors.ChannelNotFound(channel_id=channel_id)

    return channel


@router.put(
    "/{channel_id}",
    responses=errors.error_responses(
        errors.NotAuthorized,
        errors.ApplyJobRunning,
        errors.ChannelNotFound,
        errors.NotChatOwner,
        errors.ChatTooLargeToDelete,
        errors.NoPublicLink,
        # A transfer looks the successor up among the chat's admins
        errors.SuccessorNotAdmin,
        errors.FloodWait,
        errors.TelegramError,
    ),
)
async def put_decision(
    channel_id: int, body: models.DecisionRequest, ctx: ContextDep, dao: DAODep, account_id: AccountIdDep
) -> models.DecisionResponse:
    # The apply job works from the queue as it started: a change now would be applied as the old decision
    if ctx.apply.running:
        raise errors.ApplyJobRunning

    chat = await get_chat(dao, account_id, channel_id)

    decisions.check_allowed(chat, body.decision)
    successor = None

    if body.successor_id is not None:
        successor = await ctx.channels.successor(account_id, channel_id, body.successor_id)

    await decisions.decide(dao, account_id, channel_id, body.decision, utc_now(), successor)
    await dao.commit()
    return models.DecisionResponse(
        counts=await deck.counts(dao, account_id, chat.kind, db_utils.role_filter(chat.role))
    )


@router.delete(
    "/{channel_id}",
    responses=errors.error_responses(errors.NotAuthorized, errors.ApplyJobRunning, errors.ChannelNotFound),
)
async def delete_decision(
    channel_id: int, ctx: ContextDep, dao: DAODep, account_id: AccountIdDep
) -> models.UndoDecisionResponse:
    if ctx.apply.running:
        raise errors.ApplyJobRunning

    chat = await get_chat(dao, account_id, channel_id)
    removed = await decisions.undo(dao, account_id, channel_id)
    await dao.commit()
    return models.UndoDecisionResponse(
        removed=removed, counts=await deck.counts(dao, account_id, chat.kind, db_utils.role_filter(chat.role))
    )


@router.get("/trail", responses=errors.error_responses(errors.NotAuthorized))
async def get_decisions_trail(
    dao: DAODep,
    account_id: AccountIdDep,
    kind: ChatKind = ChatKind.CHANNEL,
    role: RoleFilter = RoleFilter.MEMBER,
    archive: ArchiveFilter | None = None,
) -> models.ChannelListResponse:
    channels = await dao.list_trail(account_id, kind, await deck.archive_filter(dao, account_id, archive), role)
    return models.ChannelListResponse(items=[models.Channel.from_channel(channel) for channel in channels])


@router.get("", responses=errors.error_responses(errors.NotAuthorized))
async def get_decisions(
    dao: DAODep, account_id: AccountIdDep, status: DecisionStatus | None = None
) -> models.ChannelListResponse:
    channels = await dao.list_decided(account_id, status=status)
    return models.ChannelListResponse(items=[models.Channel.from_channel(channel) for channel in channels])


@router.post("/reset", responses=errors.error_responses(errors.NotAuthorized, errors.ApplyJobRunning))
async def post_reset_decisions(
    body: models.ResetDecisionsRequest, ctx: ContextDep, dao: DAODep, account_id: AccountIdDep
) -> models.ResetDecisionsResponse:
    if ctx.apply.running:
        raise errors.ApplyJobRunning

    removed = await dao.reset_decisions(account_id, body.only, body.kind, body.role)
    await dao.commit()
    return models.ResetDecisionsResponse(
        removed=removed, counts=await deck.counts(dao, account_id, body.kind, body.role)
    )


@router.post("/retry-failed", responses=errors.error_responses(errors.NotAuthorized))
async def post_retry_failed(
    dao: DAODep, account_id: AccountIdDep, kind: ChatKind = ChatKind.CHANNEL, role: RoleFilter = RoleFilter.MEMBER
) -> models.RetryFailedResponse:
    await dao.reset_failed(account_id)
    await dao.commit()
    return models.RetryFailedResponse(counts=await deck.counts(dao, account_id, kind, role))
