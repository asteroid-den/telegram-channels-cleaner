from datetime import datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from channels_cleaner.database.models.base import Base
from channels_cleaner.database.models.decision import ChannelDecision
from channels_cleaner.enums import ChatKind, ChatRole, MediaKind


class Channel(Base):
    __tablename__ = "channels"

    account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    channel_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    title: Mapped[str]
    username: Mapped[str | None]
    about: Mapped[str | None]
    members_count: Mapped[int | None]
    unread_count: Mapped[int] = mapped_column(default=0)
    is_muted: Mapped[bool] = mapped_column(default=False)
    is_archived: Mapped[bool] = mapped_column(default=False)
    photo_file_id: Mapped[str | None]
    photo_unique_id: Mapped[str | None]
    last_post_id: Mapped[int | None]
    last_post_at: Mapped[datetime | None]
    last_post_text: Mapped[str | None]
    last_post_media: Mapped[MediaKind | None]
    full_fetched_at: Mapped[datetime | None]
    # A refusal from Telegram (CHANNEL_PRIVATE…): not asked again until full_fetched_at goes stale
    full_error: Mapped[str | None]
    synced_at: Mapped[datetime]
    # Missing from the latest sync, or left by the apply job
    gone: Mapped[bool] = mapped_column(default=False)
    pulse: Mapped[dict[str, Any] | None]
    kind: Mapped[ChatKind] = mapped_column(default=ChatKind.CHANNEL)
    role: Mapped[ChatRole] = mapped_column(default=ChatRole.MEMBER)
    # A Telegram palette id the owner picked; None: derived from the id, as Telegram does
    color: Mapped[int | None]

    # No foreign key: the tables from before SQLAlchemy have none, and a decision is written on its own anyway
    decision: Mapped[ChannelDecision | None] = relationship(
        primaryjoin=lambda: and_(
            Channel.account_id == foreign(ChannelDecision.account_id),
            Channel.channel_id == foreign(ChannelDecision.channel_id),
        ),
        lazy="joined",
        viewonly=True,
    )
