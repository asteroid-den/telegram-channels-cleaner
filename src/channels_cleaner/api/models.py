"""The API's contract: bodies are ``…Request``, answers ``…Response`` (``ok: true``), their parts plain nouns."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from channels_cleaner.api.errors import ErrorDetail
from channels_cleaner.database import models
from channels_cleaner.enums import (
    ApplyStatus,
    ArchiveFilter,
    AuthStatus,
    ChatKind,
    ChatRole,
    Decision,
    DecisionStatus,
    ItemErrorCode,
    ItemStatus,
    MediaKind,
    RoleFilter,
    SortMode,
)

THUMB_MEDIA = {MediaKind.PHOTO, MediaKind.VIDEO, MediaKind.ANIMATION}


class SendCodeRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class SignInRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class CheckPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class LogoutRequest(BaseModel):
    wipe_data: bool = False


class DecisionRequest(BaseModel):
    decision: Decision
    #: who gets the chat: one of its admins, for "transfer" only
    successor_id: int | None = None

    @model_validator(mode="after")
    def successor_for_transfer_only(self) -> Self:
        if (self.decision is Decision.TRANSFER) != (self.successor_id is not None):
            msg = "successor_id goes with the transfer decision, and only with it"
            raise ValueError(msg)

        return self


class ApplyRequest(BaseModel):
    #: the cloud password (2FA) for transfers of ownership; kept in memory for the job only. Without it the
    #: transfers wait in the queue
    password: SecretStr | None = Field(default=None, max_length=256)
    #: deletions wait in the queue unless confirmed
    confirm_deletions: bool = False


class ResetDecisionsRequest(BaseModel):
    only: Decision | None = None
    kind: ChatKind = ChatKind.CHANNEL
    role: RoleFilter = RoleFilter.MEMBER


class DeckPrefs(BaseModel):
    sort: SortMode = SortMode.DEAD
    reverse: bool = False
    archive: ArchiveFilter = ArchiveFilter.ALL


class DeckPrefsRequest(DeckPrefs):
    pass


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    username: str | None


class SyncState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    running: bool
    fetched: int
    total: int | None
    last_synced_at: str | None
    flood_wait: int | None
    error: str | None


class Pulse(BaseModel):
    #: 26 weekly post counts, oldest first; None = a week the fetched history doesn't reach
    weeks: list[int | None]
    per_week: float
    truncated: bool
    sample: int


class Channel(BaseModel):
    id: int
    kind: ChatKind
    role: ChatRole
    title: str
    username: str | None
    link: str | None
    about: str | None
    members_count: int | None
    unread_count: int
    is_muted: bool
    is_archived: bool
    avatar_url: str | None
    thumb_url: str | None
    last_post_at: datetime | None
    last_post_text: str | None
    last_post_media: MediaKind | None
    full_loaded: bool
    #: Telegram's refusal (CHANNEL_PRIVATE…), kept until the cache goes stale
    full_error: str | None = None
    decision: Decision | None
    decision_status: DecisionStatus | None
    error: str | None
    pulse: Pulse | None
    reverts: Decision | None = None
    successor_id: int | None = None
    successor_name: str | None = None

    @classmethod
    def from_channel(cls, channel: models.Channel) -> Self:
        has_thumb = channel.last_post_id is not None and channel.last_post_media in THUMB_MEDIA
        version = channel.photo_unique_id or "x"
        decision = channel.decision
        return cls(
            id=channel.channel_id,
            kind=channel.kind,
            role=channel.role,
            title=channel.title,
            username=channel.username,
            link=f"https://t.me/{channel.username}" if channel.username else None,
            about=channel.about,
            members_count=channel.members_count,
            unread_count=channel.unread_count,
            is_muted=channel.is_muted,
            is_archived=channel.is_archived,
            avatar_url=f"/api/channels/{channel.channel_id}/avatar?v={version}" if channel.photo_file_id else None,
            thumb_url=f"/api/channels/{channel.channel_id}/thumb?v={channel.last_post_id}" if has_thumb else None,
            last_post_at=channel.last_post_at,
            last_post_text=channel.last_post_text,
            last_post_media=channel.last_post_media,
            full_loaded=channel.full_fetched_at is not None,
            full_error=channel.full_error,
            decision=decision.decision if decision else None,
            decision_status=decision.status if decision else None,
            error=decision.error if decision else None,
            pulse=Pulse.model_validate(channel.pulse) if channel.pulse else None,
            reverts=decision.reverts if decision else None,
            successor_id=decision.successor_id if decision else None,
            successor_name=decision.successor_name if decision else None,
        )


class DeckCounts(BaseModel):
    total: int
    kind_totals: dict[ChatKind, int]
    role_totals: dict[RoleFilter, dict[ChatKind, int]]
    archive_totals: dict[ArchiveFilter, int]
    undecided: int
    #: pending actions of every kind and role: one review screen, one apply job
    pending: int
    #: of those, the ones outside this deck (the dot on the header switcher)
    pending_other: int
    by_decision: dict[Decision, int]
    #: final decisions in the order made, one letter each: k(eep) u(nsubscribe) m(ute) a(rchive)
    trail: str


class ApplyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_id: int
    decision: Decision
    title: str
    has_photo: bool
    status: ItemStatus
    error: str | None
    #: why Telegram refused an owner's action, when the UI has more to say about it than ``error``
    error_code: ItemErrorCode | None
    #: seconds until Telegram allows the transfer (error_code "too_fresh")
    retry_after: int | None
    reverts: Decision | None
    role: ChatRole
    successor_name: str | None


class ApplyState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int | None
    status: ApplyStatus
    total: int
    done: int
    failed: int
    current: int | None
    #: a Unix time
    flood_wait_until: float | None
    items: list[ApplyItem]
    #: left in the queue: transfers started without the password, deletions without the confirmation
    held_transfers: int
    held_deletions: int


class ChatAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    username: str | None
    #: may add admins: the one an owner usually hands the chat to
    can_promote: bool


class Account(BaseModel):
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    avatar_url: str | None
    active: bool
    chats: int
    #: decisions waiting for the apply job in that account
    pending: int


class ExportRow(BaseModel):
    channel_id: int
    title: str
    username: str | None
    link: str | None
    members_count: int | None
    last_post_at: datetime | None
    unsubscribed_at: datetime | None


class OkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: Literal[True] = True


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    type: str
    message: str
    reason: str | None = None
    retry_after: int | None = None
    channel_id: int | None = None
    details: list[ErrorDetail] | None = None


class HealthResponse(OkResponse):
    version: str
    mock: bool


class AuthStateResponse(OkResponse):
    status: AuthStatus
    user: User | None
    qr_url: str | None
    qr_expires_at: datetime | None
    password_hint: str | None
    phone: str | None
    error: str | None


class SyncStateResponse(OkResponse, SyncState):
    pass


class DeckResponse(OkResponse):
    items: list[Channel]
    counts: DeckCounts
    sync: SyncState


class ChannelResponse(OkResponse, Channel):
    pass


class ChannelListResponse(OkResponse):
    items: list[Channel]


class DecisionResponse(OkResponse):
    counts: DeckCounts


class UndoDecisionResponse(OkResponse):
    removed: bool
    counts: DeckCounts


class ResetDecisionsResponse(OkResponse):
    removed: int
    counts: DeckCounts


class RetryFailedResponse(OkResponse):
    counts: DeckCounts


class AdminsResponse(OkResponse):
    items: list[ChatAdmin]


class ApplyStateResponse(OkResponse, ApplyState):
    pass


class DeckPrefsResponse(OkResponse, DeckPrefs):
    pass


class StatsResponse(OkResponse):
    subscribed: int
    unread_total: int
    unread_cleared: int
    decisions: dict[Decision, dict[DecisionStatus, int]]
    last_post_age: dict[str, int]


class AccountsResponse(OkResponse):
    items: list[Account]
