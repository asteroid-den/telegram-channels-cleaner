from datetime import datetime

from channels_cleaner.api.errors import ChatTooLargeToDelete, NoPublicLink, NotChatOwner
from channels_cleaner.database import DAO
from channels_cleaner.database.models import Channel
from channels_cleaner.enums import (
    ACTION_DECISIONS,
    OWNER_ACTIONS,
    REVERSIBLE_ACTIONS,
    ChatRole,
    Decision,
    DecisionStatus,
)
from channels_cleaner.telegram import DELETE_LIMIT, ChatAdmin


def check_allowed(chat: Channel, decision: Decision) -> None:
    """Refuses a decision the user's place in the chat doesn't allow; Telegram would refuse it on apply anyway."""
    if decision in OWNER_ACTIONS and chat.role is not ChatRole.OWNER:
        raise NotChatOwner(channel_id=chat.channel_id)

    if decision is Decision.DELETE and chat.members_count is not None and chat.members_count > DELETE_LIMIT:
        raise ChatTooLargeToDelete(channel_id=chat.channel_id, members_count=chat.members_count)

    if decision is Decision.FREE_LINK and chat.username is None:
        raise NoPublicLink(channel_id=chat.channel_id)


def full_name(user: ChatAdmin) -> str:
    return f"{user.first_name} {user.last_name or ''}".strip() or (user.username or str(user.id))


async def decide(
    dao: DAO,
    account_id: int,
    channel_id: int,
    decision: Decision,
    now: datetime,
    successor: ChatAdmin | None = None,
) -> None:
    current = await dao.get_decision(account_id, channel_id)
    # What the app has already done to this chat in Telegram (a later change undoes it)
    in_telegram: Decision | None = None

    if current is not None:
        if current.reverts is not None:
            in_telegram = current.reverts

        elif current.status is DecisionStatus.APPLIED and current.decision in REVERSIBLE_ACTIONS:
            in_telegram = current.decision

    # "Later" can't take an applied action back
    if decision is Decision.SKIP and in_telegram is not None:
        decision = in_telegram

    reverts: Decision | None = None
    applied_at: datetime | None

    if in_telegram is decision:
        # Back to what Telegram already has
        status = DecisionStatus.APPLIED
        applied_at = current.applied_at if current is not None else now

    elif in_telegram is not None:
        status, reverts, applied_at = DecisionStatus.PENDING, in_telegram, None

    else:
        # "keep" and "skip" need no Telegram call, so they are final right away
        status = DecisionStatus.PENDING if decision in ACTION_DECISIONS else DecisionStatus.APPLIED
        applied_at = None if status is DecisionStatus.PENDING else now

    # A changed decision keeps its place in the order of the pass; "later" never had one
    keep_place = current is not None and current.decision is not Decision.SKIP and decision is not Decision.SKIP
    decided_at = current.decided_at if keep_place and current is not None else now

    await dao.save_decision(
        account_id,
        channel_id,
        decision=decision,
        status=status,
        decided_at=decided_at,
        applied_at=applied_at,
        reverts=reverts,
        successor_id=successor.id if successor is not None else None,
        successor_name=full_name(successor) if successor is not None else None,
    )


async def undo(dao: DAO, account_id: int, channel_id: int) -> bool:
    current = await dao.get_decision(account_id, channel_id)

    # Undoing a change of an applied action restores that action as it is in Telegram
    if current is not None and current.reverts is not None:
        await dao.restore_reverted(account_id, channel_id)
        return True

    return await dao.delete_decision(account_id, channel_id)
