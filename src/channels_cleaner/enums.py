"""Values are the lowercase member names: the same strings are in the database, the API and the UI."""

from enum import StrEnum, auto
from typing import Literal


class ChatKind(StrEnum):
    CHANNEL = auto()
    # Forums too: a separate type in Kurigram, a supergroup for Telegram
    SUPERGROUP = auto()


class ChatRole(StrEnum):
    MEMBER = auto()
    ADMIN = auto()
    OWNER = auto()


class MediaKind(StrEnum):
    PHOTO = auto()
    VIDEO = auto()
    ANIMATION = auto()
    DOCUMENT = auto()
    AUDIO = auto()
    VOICE = auto()
    POLL = auto()
    STICKER = auto()
    OTHER = auto()


class Decision(StrEnum):
    KEEP = auto()
    UNSUBSCRIBE = auto()
    MUTE = auto()
    ARCHIVE = auto()
    # "Later": back of the deck, forgotten on the next launch
    SKIP = auto()
    # The owner's own actions: hand the chat to an admin and leave, delete it, make it private
    TRANSFER = auto()
    DELETE = auto()
    FREE_LINK = auto()


class DecisionStatus(StrEnum):
    PENDING = auto()
    APPLIED = auto()
    FAILED = auto()


class JobStatus(StrEnum):
    RUNNING = auto()
    FINISHED = auto()
    CANCELLED = auto()
    ERROR = auto()
    # Still running when the app stopped
    INTERRUPTED = auto()


class SortMode(StrEnum):
    # Never posted first, then the longest silence
    DEAD = auto()
    UNREAD = auto()


class ArchiveFilter(StrEnum):
    ALL = auto()
    ACTIVE = auto()
    ARCHIVED = auto()


class RoleFilter(StrEnum):
    MEMBER = auto()
    MANAGED = auto()


ACTION_DECISIONS = (
    Decision.UNSUBSCRIBE,
    Decision.MUTE,
    Decision.ARCHIVE,
    Decision.TRANSFER,
    Decision.DELETE,
    Decision.FREE_LINK,
)
#: actions after which the chat is gone from the user's list
LEAVING_ACTIONS = (Decision.UNSUBSCRIBE, Decision.TRANSFER, Decision.DELETE)
#: actions only the chat's owner can take
OWNER_ACTIONS = (Decision.TRANSFER, Decision.DELETE, Decision.FREE_LINK)
#: applied actions the app can take back (a left chat is gone for good)
REVERSIBLE_ACTIONS = (Decision.MUTE, Decision.ARCHIVE)

# The states the UI sees, never stored as such
AuthStatus = Literal["starting", "unauthorized", "qr", "code", "password", "authorized"]
#: "idle" before any job; the rest is written down as a JobStatus
ApplyStatus = Literal["idle", "running", "finished", "cancelled", "error"]
ItemStatus = Literal["queued", "running", "done", "failed"]
#: why Telegram refused an owner's action, for the UI to explain
ItemErrorCode = Literal["password_invalid", "password_missing", "too_fresh", "too_large"]
