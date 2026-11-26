from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime

from channels_cleaner.enums import ChatKind, ChatRole, MediaKind


@dataclass(slots=True, frozen=True)
class TgUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None


@dataclass(slots=True, frozen=True)
class QrToken:
    url: str
    expires_at: datetime


@dataclass(slots=True)
class ChannelInfo:
    id: int
    title: str
    username: str | None
    unread_count: int
    is_muted: bool
    is_archived: bool
    members_count: int | None
    photo_file_id: str | None
    photo_unique_id: str | None
    last_post_id: int | None
    last_post_at: datetime | None
    last_post_text: str | None
    last_post_media: MediaKind | None
    kind: ChatKind = ChatKind.CHANNEL
    role: ChatRole = ChatRole.MEMBER
    #: the colour the chat's owner picked (a Telegram palette id); None: Telegram derives one from the id
    color: int | None = None


@dataclass(slots=True, frozen=True)
class ChatAdmin:
    """Someone who could take over the chat: a live admin, not a bot, not the user."""

    id: int
    first_name: str
    last_name: str | None
    username: str | None
    #: may add admins: the one an owner usually hands the chat to
    can_promote: bool


@dataclass(slots=True, frozen=True)
class ChannelFull:
    about: str | None
    members_count: int | None


#: Telegram deletes chats only up to about this many members (CHANNEL_TOO_LARGE above it)
DELETE_LIMIT = 1000
#: Bot API ids of channels and supergroups are -100 followed by the channel's own id
CHANNEL_ID_OFFSET = -1_000_000_000_000
#: how many colours Telegram picks an empty avatar from (red, orange, violet, green, cyan, blue, pink)
COLOR_COUNT = 7


def color_index(channel_id: int, color: int | None) -> int:
    """Telegram's colour of a chat: the one its owner picked, else its own id (without the -100) modulo 7.

    As Telegram Desktop's ``DecideColorIndex``; the UI maps it to Telegram's avatar gradients.
    """
    return (color if color is not None else CHANNEL_ID_OFFSET - channel_id) % COLOR_COUNT


#: the session of the versions with one account; later ones get a name of their own
LEGACY_SESSION = "account"


def new_session_name() -> str:
    return f"session-{secrets.token_hex(4)}"


class GatewayError(Exception):
    pass


class PasswordNeededError(GatewayError):
    """The account has a cloud password (2FA); ``check_password`` must be called next."""


class InvalidCodeError(GatewayError):
    pass


class InvalidPasswordError(GatewayError):
    pass


class InvalidPhoneError(GatewayError):
    pass


class QrExpiredError(GatewayError):
    pass


class NotAuthorizedError(GatewayError):
    pass


class RequestRefusedError(GatewayError):
    """A 4xx (CHANNEL_PRIVATE…): the same answer if asked again soon, unlike a dropped connection."""


class PasswordMissingError(GatewayError):
    """A transfer of ownership needs a cloud password (2FA), and the account has none."""


class TooFreshError(GatewayError):
    """The session or the cloud password is too new for a transfer of ownership."""

    def __init__(self, message: str, seconds: int) -> None:
        super().__init__(message)
        self.seconds = seconds


class ChatTooLargeError(GatewayError):
    """Telegram deletes only chats up to about a thousand members."""


class FloodWaitError(GatewayError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Flood wait for {seconds}s")
        self.seconds = seconds
