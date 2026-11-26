from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Coroutine
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from channels_cleaner.api.errors import ChannelNotFound, NotChatOwner, SuccessorNotAdmin
from channels_cleaner.config import Settings
from channels_cleaner.database import DAO, DatabaseManager, utc_now
from channels_cleaner.database.models import Channel
from channels_cleaner.enums import ChatRole, MediaKind
from channels_cleaner.pulse import HISTORY_LIMIT, compute_pulse
from channels_cleaner.telegram import ChannelFull, ChatAdmin, FloodWaitError, RequestRefusedError, TelegramGateway

log = logging.getLogger(__name__)

NONE_MARKER = ".none"
#: how long a chat's admins are taken as known: long enough to pick one and confirm, short enough to see a change
ADMINS_TTL = 600


class ChannelsService:
    def __init__(self, gateway: TelegramGateway, database: DatabaseManager, settings: Settings) -> None:
        self.gateway = gateway
        self.database = database
        self.settings = settings
        # Telegram is touchy about GetFullChannel bursts: one at a time is plenty for a deck
        self.full_semaphore = asyncio.Semaphore(1)
        self.media_semaphore = asyncio.Semaphore(2)
        self.inflight: dict[tuple[str, int], asyncio.Future[object]] = {}
        # Until when (time.monotonic) Telegram asked us to leave each kind of request alone. A flood wait on one card
        # holds for the next ones too: they would only get the same answer, and Telegram lengthens waits for that.
        self.cooldowns: dict[str, float] = {}
        # (account, chat) → (time.monotonic of the answer, the admins)
        self.admins_cache: dict[tuple[int, int], tuple[float, list[ChatAdmin]]] = {}

    def reset(self) -> None:
        """Another account is on: a flood wait was the last one's."""
        self.cooldowns.clear()
        self.admins_cache.clear()

    def check_cooldown(self, kind: str) -> None:
        left = self.cooldowns.get(kind, 0) - time.monotonic()

        if left > 0:
            raise FloodWaitError(math.ceil(left))

    def cool_down(self, kind: str, exc: FloodWaitError) -> None:
        until = time.monotonic() + exc.seconds
        self.cooldowns[kind] = max(self.cooldowns.get(kind, 0), until)
        log.info("Telegram asks to wait %s s before the next %s request", exc.seconds, kind)

    async def get_row(self, account_id: int, channel_id: int) -> Channel:
        async with self.database.session() as session:
            row = await DAO(session).get_channel(account_id, channel_id)

        if row is None:
            raise ChannelNotFound(channel_id=channel_id)

        return row

    async def admins(self, account_id: int, channel_id: int) -> list[ChatAdmin]:
        """Who could take over a chat the user owns."""
        row = await self.get_row(account_id, channel_id)

        if row.role is not ChatRole.OWNER:
            raise NotChatOwner(channel_id=channel_id)

        key = (account_id, channel_id)
        cached = self.admins_cache.get(key)

        if cached is not None and time.monotonic() - cached[0] < ADMINS_TTL:
            return cached[1]

        self.check_cooldown("admins")

        try:
            admins = await self.gateway.get_admins(channel_id)

        except FloodWaitError as exc:
            self.cool_down("admins", exc)
            raise

        self.admins_cache[key] = (time.monotonic(), admins)
        return admins

    async def successor(self, account_id: int, channel_id: int, user_id: int) -> ChatAdmin:
        admin = next((admin for admin in await self.admins(account_id, channel_id) if admin.id == user_id), None)

        if admin is None:
            raise SuccessorNotAdmin(channel_id=channel_id, user_id=user_id)

        return admin

    def is_fresh(self, fetched_at: datetime | None) -> bool:
        if fetched_at is None:
            return False

        return utc_now() - fetched_at < timedelta(hours=self.settings.full_info_ttl_hours)

    async def get_full(self, account_id: int, channel_id: int) -> Channel:
        row = await self.get_row(account_id, channel_id)

        # Rows cached before the pulse existed are refreshed once to get it; a refusal stands as long as an answer would
        if self.is_fresh(row.full_fetched_at) and (row.pulse is not None or row.full_error is not None):
            return row

        self.check_cooldown("full")
        key = ("full", channel_id)

        if key in self.inflight:
            await self.inflight[key]

        else:
            future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
            self.inflight[key] = future

            try:
                await self.fetch_full(account_id, channel_id)

            finally:
                # Waiters just re-read the row; if this fetch failed they get it without extras.
                future.set_result(None)
                self.inflight.pop(key, None)

        return await self.get_row(account_id, channel_id)

    async def fetch_full(self, account_id: int, channel_id: int) -> None:
        async with self.full_semaphore:
            # A card that waited for the semaphore behind a flood wait gets it too, without asking
            self.check_cooldown("full")

            try:
                full: ChannelFull = await self.gateway.get_full(channel_id)

            except FloodWaitError as exc:
                self.cool_down("full", exc)
                raise

            except RequestRefusedError as exc:
                async with self.database.session() as session:
                    dao = DAO(session)
                    await dao.save_full_refused(account_id, channel_id, str(exc), utc_now())
                    await dao.commit()

                return

            try:
                dates: list[datetime] | None = await self.gateway.recent_post_dates(channel_id, HISTORY_LIMIT)

            # The full info is in hand: keep it, the pulse comes with a later fetch (a row without one is refetched)
            except FloodWaitError as exc:
                self.cool_down("full", exc)
                dates = None

        async with self.database.session() as session:
            dao = DAO(session)
            pulse = compute_pulse(dates, limit=HISTORY_LIMIT) if dates is not None else None
            await dao.save_full(account_id, channel_id, full, pulse, utc_now())
            await dao.commit()

    def media_dir(self, account_id: int) -> Path:
        path = self.settings.media_dir / str(account_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def cached_file(directory: Path, stem: str) -> Path | bool | None:
        for candidate in directory.glob(f"{stem}.*"):
            if candidate.suffix == NONE_MARKER:
                return False

            return candidate

        return None

    def own_photo(self, account_id: int) -> Path | None:
        # Read only: asking about an unknown account doesn't make a folder for it
        return next((self.settings.media_dir / str(account_id)).glob("me.*"), None)

    async def refresh_own_photo(self, account_id: int) -> None:
        """Fetches the user's photo after a login; one removed in Telegram goes here too."""
        directory = self.media_dir(account_id)
        before = list(directory.glob("me.*"))
        path = await self.download(self.gateway.download_own_photo(directory / "me.jpg"))

        for old in before:
            if old != path:
                old.unlink(missing_ok=True)

    async def avatar(self, account_id: int, channel_id: int) -> Path | None:
        row = await self.get_row(account_id, channel_id)

        if not row.photo_file_id:
            return None

        directory = self.media_dir(account_id)
        stem = f"avatar_{channel_id}_{row.photo_unique_id or 'x'}"
        cached = self.cached_file(directory, stem)

        if cached is False:
            return None

        if isinstance(cached, Path):
            return cached

        download = self.gateway.download_avatar(channel_id, row.photo_file_id, directory / f"{stem}.jpg")
        path = await self.download(download)

        if path is None:
            (directory / f"{stem}{NONE_MARKER}").touch()

        return path

    async def post_thumb(self, account_id: int, channel_id: int) -> Path | None:
        row = await self.get_row(account_id, channel_id)

        if not row.last_post_id or row.last_post_media not in {MediaKind.PHOTO, MediaKind.VIDEO, MediaKind.ANIMATION}:
            return None

        directory = self.media_dir(account_id)
        stem = f"thumb_{channel_id}_{row.last_post_id}"
        cached = self.cached_file(directory, stem)

        if cached is False:
            return None

        if isinstance(cached, Path):
            return cached

        path = await self.download(
            self.gateway.download_post_thumb(channel_id, row.last_post_id, directory / f"{stem}.jpg")
        )

        if path is None:
            (directory / f"{stem}{NONE_MARKER}").touch()

        return path

    async def download(self, download: Coroutine[Any, Any, Path | None]) -> Path | None:
        try:
            self.check_cooldown("media")

            async with self.media_semaphore:
                self.check_cooldown("media")

                try:
                    return await download

                except FloodWaitError as exc:
                    self.cool_down("media", exc)
                    raise

        finally:
            # Never awaited when the cooldown refused it: closed, or Python warns about a coroutine never awaited
            download.close()
