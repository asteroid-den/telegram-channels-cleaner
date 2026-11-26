from sqlalchemy import ColumnElement, literal_column, true

from channels_cleaner.database.models import Channel
from channels_cleaner.enums import ArchiveFilter, ChatRole, Decision, RoleFilter

TRAIL_CODES = {
    Decision.KEEP: "k",
    Decision.UNSUBSCRIBE: "u",
    Decision.MUTE: "m",
    Decision.ARCHIVE: "a",
    Decision.TRANSFER: "t",
    Decision.DELETE: "d",
    Decision.FREE_LINK: "l",
}

# Ties on decided_at (same microsecond) keep the order of insertion; decisions has no column of its own for that
DECISION_ROWID = literal_column("decisions.rowid")


def archive_is(archive: ArchiveFilter) -> ColumnElement[bool]:
    match archive:
        case ArchiveFilter.ACTIVE:
            return Channel.is_archived.is_(False)
        case ArchiveFilter.ARCHIVED:
            return Channel.is_archived.is_(True)
        case _:
            return true()


def role_is(role: RoleFilter) -> ColumnElement[bool]:
    if role is RoleFilter.MANAGED:
        return Channel.role != ChatRole.MEMBER

    return Channel.role == ChatRole.MEMBER


def role_filter(role: ChatRole) -> RoleFilter:
    return RoleFilter.MEMBER if role is ChatRole.MEMBER else RoleFilter.MANAGED
