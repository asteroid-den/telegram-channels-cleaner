from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from channels_cleaner.database.models.base import Base
from channels_cleaner.enums import Decision, DecisionStatus


class ChannelDecision(Base):
    __tablename__ = "decisions"

    account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    channel_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    decision: Mapped[Decision]
    status: Mapped[DecisionStatus]
    # Kept when the decision is changed: the order of the pass, which the progress bar shows
    decided_at: Mapped[datetime]
    applied_at: Mapped[datetime | None]
    error: Mapped[str | None]
    # A mute or archive the app already applied and the current decision takes back first
    reverts: Mapped[Decision | None]
    # Who gets the chat on a transfer; the name as it was when chosen, for the review screen
    successor_id: Mapped[int | None]
    successor_name: Mapped[str | None]
