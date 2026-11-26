from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from channels_cleaner.database.models.base import Base


class Device(Base):
    """A phone (or any other browser in the local network) the user paired; app-wide, not per account."""

    __tablename__ = "devices"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    user_agent: Mapped[str]
    # SHA-256 of the cookie it shows: the token itself is never stored
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    last_ip: Mapped[str | None]
