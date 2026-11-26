from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pyrogram import Client, enums, errors
from pyrogram.qrlogin import QRLogin
from pyrogram.raw.functions.channels.get_full_channel import GetFullChannel
from pyrogram.raw.functions.messages.get_history import GetHistory
from pyrogram.raw.types.auth.login_token import LoginToken
from pyrogram.raw.types.input_channel import InputChannel
from pyrogram.raw.types.input_peer_channel import InputPeerChannel
from pyrogram.raw.types.message import Message

from channels_cleaner.config import Settings
from channels_cleaner.enums import ChatKind, ChatRole, MediaKind
from channels_cleaner.telegram import device_profiles
from channels_cleaner.telegram.device_profiles import DeviceProfile
from channels_cleaner.telegram.types import (
    LEGACY_SESSION,
    ChannelFull,
    ChannelInfo,
    ChatAdmin,
    ChatTooLargeError,
    FloodWaitError,
    GatewayError,
    InvalidCodeError,
    InvalidPasswordError,
    InvalidPhoneError,
    NotAuthorizedError,
    PasswordMissingError,
    PasswordNeededError,
    QrExpiredError,
    QrToken,
    RequestRefusedError,
    TgUser,
    TooFreshError,
)

log = logging.getLogger(__name__)

MEDIA_KINDS: dict[Any, MediaKind] = {
    enums.MessageMediaType.PHOTO: MediaKind.PHOTO,
    enums.MessageMediaType.LIVE_PHOTO: MediaKind.PHOTO,
    enums.MessageMediaType.VIDEO: MediaKind.VIDEO,
    enums.MessageMediaType.VIDEO_NOTE: MediaKind.VIDEO,
    enums.MessageMediaType.ANIMATION: MediaKind.ANIMATION,
    enums.MessageMediaType.DOCUMENT: MediaKind.DOCUMENT,
    enums.MessageMediaType.AUDIO: MediaKind.AUDIO,
    enums.MessageMediaType.VOICE: MediaKind.VOICE,
    enums.MessageMediaType.POLL: MediaKind.POLL,
    enums.MessageMediaType.STICKER: MediaKind.STICKER,
}

# A forum (a supergroup with topics) is a separate type in Kurigram but a supergroup for Telegram
# and for its 1000 channels-and-supergroups limit. Basic groups and channel DMs are not covered.
CHAT_KINDS: dict[Any, ChatKind] = {
    enums.ChatType.CHANNEL: ChatKind.CHANNEL,
    enums.ChatType.SUPERGROUP: ChatKind.SUPERGROUP,
    enums.ChatType.FORUM: ChatKind.SUPERGROUP,
}


@contextlib.contextmanager
def telegram_errors() -> Iterator[None]:
    """Kurigram's errors as the gateway's own: the services and the API know only those."""
    try:
        yield

    except errors.FloodWait as exc:
        raise FloodWaitError(int(exc.value or 0)) from exc

    except REFUSED as exc:
        raise RequestRefusedError(str(exc.MESSAGE or exc)) from exc

    except errors.RPCError as exc:
        raise GatewayError(str(exc.MESSAGE or exc)) from exc

    except (OSError, TimeoutError) as exc:
        raise offline_error(exc) from exc


#: Telegram's answers that won't change if asked again soon: the chat is private, banned, gone, or the request is wrong
REFUSED = (errors.BadRequest, errors.Forbidden, errors.NotFound, errors.NotAcceptable)


def offline_error(exc: BaseException) -> GatewayError:
    return GatewayError(f"No connection to Telegram: {exc or type(exc).__name__}")


# Telegram uses this as "muted forever".
MUTE_FOREVER = timedelta(days=365 * 10)


def to_user(user: Any) -> TgUser:  # noqa: ANN401 - a pyrogram User, untyped
    return TgUser(
        id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name,
        username=user.username,
    )


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    # Kurigram's dates are naive local times (datetime.fromtimestamp), not UTC: astimezone reads a naive one as local
    return value.astimezone(UTC)


class KurigramGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Client | None = None
        self._profile: DeviceProfile | None = None
        self.qr_login: QRLogin | None = None
        self.phone: str | None = None
        self.phone_code_hash: str | None = None
        self.started = False
        self.session = LEGACY_SESSION

    @property
    def device_profile(self) -> DeviceProfile | None:
        return self._profile

    @property
    def profile_path(self) -> Path:
        return self.settings.sessions_dir / f"{self.session}.device.json"

    def make_client(self) -> Client:
        self._profile = device_profiles.load_or_create(self.profile_path)
        return Client(
            self.session,
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            workdir=self.settings.sessions_dir,
            client_platform=enums.ClientPlatform.DESKTOP,
            sleep_threshold=30,
            **self._profile.client_kwargs(),
        )

    @property
    def client(self) -> Client:
        if self._client is None or not self.started:
            msg = "Telegram client is not authorized"
            raise NotAuthorizedError(msg)

        return self._client

    async def start(self, session: str) -> TgUser | None:
        self.session = session
        self._client = self.make_client()
        # Mirror the first lines of ``Client.start`` so a bare ``connect`` works on our loop.
        self._client._loop = asyncio.get_running_loop()  # noqa: SLF001
        rebuild = getattr(self._client, "_rebuild_loop_bound_state", None)

        if rebuild is not None:
            rebuild()

        authorized = await self._client.connect()

        if not authorized:
            return None

        return await self.finish_login()

    async def finish_login(self) -> TgUser:
        client = self.pending_client()
        await client.disconnect()

        try:
            await client.start()

        except (errors.AuthKeyUnregistered, errors.Unauthorized) as exc:
            # Session revoked from another device: start from scratch.
            log.warning("Stored session is no longer valid: %s", exc)
            await self.forget_session()
            msg = "Session was revoked, please log in again"
            raise NotAuthorizedError(msg) from exc

        self.started = True
        self.qr_login = None
        return to_user(client.me)

    async def stop(self) -> None:
        if self._client is None:
            return

        with contextlib.suppress(Exception):
            if self.started:
                await self._client.stop()

            elif self._client.is_connected:
                await self._client.disconnect()

        self.started = False

    async def forget_session(self) -> None:
        await self.stop()

        for path in self.settings.sessions_dir.glob(f"{self.session}.*"):
            path.unlink(missing_ok=True)

        self._client = None

    def pending_client(self) -> Client:
        if self._client is None or not self._client.is_connected:
            msg = "Client is not connected"
            raise GatewayError(msg)

        if self.started:
            msg = "Already authorized"
            raise GatewayError(msg)

        return self._client

    async def qr_export(self) -> QrToken:
        client = self.pending_client()

        if self.qr_login is None:
            self.qr_login = QRLogin(client)

        try:
            await self.qr_login.recreate()

        except errors.SessionPasswordNeeded as exc:
            raise PasswordNeededError from exc

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        token = self.qr_login.r

        if not isinstance(token, LoginToken):
            msg = f"Unexpected QR login answer: {type(token).__name__}"
            raise GatewayError(msg)

        expires = datetime.fromtimestamp(token.expires, tz=UTC)
        return QrToken(url=self.qr_login.url, expires_at=expires)

    async def qr_wait(self) -> TgUser:
        if self.qr_login is None:
            msg = "QR login was not started"
            raise GatewayError(msg)

        try:
            user = await self.qr_login.wait()

        except TimeoutError as exc:
            raise QrExpiredError from exc

        except errors.AuthTokenExpired as exc:
            raise QrExpiredError from exc

        except errors.SessionPasswordNeeded as exc:
            raise PasswordNeededError from exc

        if user is None:
            raise QrExpiredError

        return await self.finish_login()

    async def send_code(self, phone: str) -> None:
        client = self.pending_client()
        self.qr_login = None

        try:
            sent = await client.send_code(phone)

        except (errors.PhoneNumberInvalid, errors.PhoneNumberBanned) as exc:
            raise InvalidPhoneError(str(exc.MESSAGE)) from exc

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        self.phone = phone
        self.phone_code_hash = sent.phone_code_hash

    async def sign_in_code(self, code: str) -> TgUser:
        client = self.pending_client()

        if not self.phone or not self.phone_code_hash:
            msg = "Request a code first"
            raise GatewayError(msg)

        try:
            result = await client.sign_in(self.phone, self.phone_code_hash, code)

        except (errors.PhoneCodeInvalid, errors.PhoneCodeExpired) as exc:
            raise InvalidCodeError(str(exc.MESSAGE)) from exc

        except errors.SessionPasswordNeeded as exc:
            raise PasswordNeededError from exc

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        if result is False or not hasattr(result, "id"):
            msg = "This phone number has no Telegram account"
            raise GatewayError(msg)

        return await self.finish_login()

    async def password_hint(self) -> str | None:
        hint: str | None = await self.pending_client().get_password_hint()
        return hint

    async def check_password(self, password: str) -> TgUser:
        client = self.pending_client()

        try:
            await client.check_password(password)

        except errors.PasswordHashInvalid as exc:
            raise InvalidPasswordError(str(exc.MESSAGE)) from exc

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        return await self.finish_login()

    async def log_out(self) -> None:
        if self._client is not None and self.started:
            with contextlib.suppress(Exception):
                await self._client.log_out()

            self.started = False

        await self.forget_session()
        self.profile_path.unlink(missing_ok=True)
        self._profile = None

    async def iter_channels(self) -> AsyncIterator[ChannelInfo]:
        client = self.client
        now = datetime.now(UTC)

        with telegram_errors():
            async for dialog in client.get_dialogs():
                chat = dialog.chat

                kind = CHAT_KINDS.get(chat.type) if chat is not None else None

                if chat is None or kind is None:
                    continue

                yield self.channel_info(dialog, now, kind)

    @staticmethod
    def channel_info(dialog: Any, now: datetime, kind: ChatKind) -> ChannelInfo:  # noqa: ANN401 - a pyrogram Dialog, untyped
        chat = dialog.chat
        top = dialog.top_message
        muted = False
        notify = getattr(getattr(dialog, "raw", None), "notify_settings", None)

        if notify is not None:
            mute_until = getattr(notify, "mute_until", None)
            muted = bool(getattr(notify, "silent", False)) or bool(mute_until and mute_until > now.timestamp())

        text = None
        media: MediaKind | None = None

        if top is not None:
            text = top.text or top.caption

            if top.media is not None:
                media = MEDIA_KINDS.get(top.media, MediaKind.OTHER)

        photo = chat.photo
        return ChannelInfo(
            id=chat.id,
            title=chat.title or "",
            username=chat.username,
            unread_count=dialog.unread_messages_count or 0,
            is_muted=muted,
            is_archived=dialog.folder_id == 1,
            members_count=chat.members_count,
            photo_file_id=photo.small_file_id if photo else None,
            photo_unique_id=photo.small_photo_unique_id if photo else None,
            last_post_id=top.id if top is not None else None,
            last_post_at=utc(top.date) if top is not None else None,
            last_post_text=str(text) if text else None,
            last_post_media=media,
            kind=kind,
            role=ChatRole.OWNER if chat.is_creator else ChatRole.ADMIN if chat.is_admin else ChatRole.MEMBER,
            color=getattr(chat, "accent_color_id", None),
        )

    async def get_full(self, channel_id: int) -> ChannelFull:
        # Raw GetFullChannel (supergroups are channels too): get_chat can't be told not to sleep through a flood wait,
        # and a sleep of up to sleep_threshold here holds up every other card. The service decides what to do instead.
        with telegram_errors():
            peer = await self.client.resolve_peer(channel_id)

            if not isinstance(peer, InputPeerChannel):
                return ChannelFull(about=None, members_count=None)

            result = await self.client.invoke(
                GetFullChannel(channel=InputChannel(channel_id=peer.channel_id, access_hash=peer.access_hash)),
                sleep_threshold=0,
            )

        full = result.full_chat
        return ChannelFull(about=full.about or None, members_count=getattr(full, "participants_count", None))

    async def recent_post_dates(self, channel_id: int, limit: int) -> list[datetime]:
        # Raw GetHistory: one request, no message parsing (the high-level iterator parses
        # every message and may fetch replies on top).
        client = self.client

        try:
            peer = await client.resolve_peer(channel_id)

            if peer is None:
                return []

            result = await client.invoke(
                GetHistory(
                    peer=peer,
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                ),
                sleep_threshold=0,
            )

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        except errors.RPCError as exc:
            log.info("History fetch failed for %s: %s", channel_id, exc)
            return []

        dates = [
            datetime.fromtimestamp(m.date, tz=UTC) for m in getattr(result, "messages", []) if isinstance(m, Message)
        ]
        return sorted(dates, reverse=True)

    async def download_avatar(self, channel_id: int, file_id: str, dest: Path) -> Path | None:
        try:
            result = await self.client.download_media(file_id, file_name=str(dest))

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        except errors.RPCError as exc:
            log.info("Avatar download failed for %s: %s", channel_id, exc)
            return None

        # Not "no picture": that would be remembered, while the connection comes back
        except (OSError, TimeoutError) as exc:
            raise offline_error(exc) from exc

        return Path(result) if isinstance(result, str) else None

    async def download_own_photo(self, dest: Path) -> Path | None:
        photo = getattr(self.client.me, "photo", None)

        if photo is None:
            return None

        try:
            result = await self.client.download_media(photo.small_file_id, file_name=str(dest))

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        except errors.RPCError as exc:
            log.info("Profile photo download failed: %s", exc)
            return None

        except (OSError, TimeoutError) as exc:
            raise offline_error(exc) from exc

        return Path(result) if isinstance(result, str) else None

    async def download_post_thumb(self, channel_id: int, message_id: int, dest: Path) -> Path | None:
        try:
            message = await self.client.get_messages(channel_id, message_id)

            if message is None or getattr(message, "empty", False):
                return None

            thumbs = None

            for attr in ("photo", "video", "animation", "document"):
                media = getattr(message, attr, None)

                if media is not None:
                    thumbs = getattr(media, "thumbs", None)
                    break

            if not thumbs:
                return None

            biggest = max(thumbs, key=lambda t: (t.width or 0) * (t.height or 0))
            result = await self.client.download_media(biggest, file_name=str(dest))

        except errors.FloodWait as exc:
            raise FloodWaitError(int(exc.value or 0)) from exc

        except errors.RPCError as exc:
            log.info("Thumbnail download failed for %s/%s: %s", channel_id, message_id, exc)
            return None

        # Not "no picture": that would be remembered, while the connection comes back
        except (OSError, TimeoutError) as exc:
            raise offline_error(exc) from exc

        return Path(result) if isinstance(result, str) else None

    async def leave(self, channel_id: int) -> None:
        with telegram_errors():
            try:
                await self.client.leave_chat(channel_id)

            # Already gone: the end state asked for
            except (errors.UserNotParticipant, errors.ChannelPrivate):
                return

    async def mute(self, channel_id: int) -> None:
        with telegram_errors():
            await self.client.update_chat_notifications(channel_id, mute=True, mute_until=MUTE_FOREVER)

    async def archive(self, channel_id: int) -> None:
        with telegram_errors():
            await self.client.archive_chats(channel_id)

    async def unmute(self, channel_id: int) -> None:
        with telegram_errors():
            await self.client.update_chat_notifications(channel_id, mute=False)

    async def unarchive(self, channel_id: int) -> None:
        with telegram_errors():
            await self.client.unarchive_chats(channel_id)

    async def get_admins(self, channel_id: int) -> list[ChatAdmin]:
        admins: list[ChatAdmin] = []

        with telegram_errors():
            async for member in self.client.get_chat_members(channel_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
                user = member.user

                # Only someone who can take the chat over: not a bot, a deleted account or the user
                if user is None or user.is_bot or user.is_deleted or user.is_self:
                    continue

                privileges = member.privileges
                admins.append(
                    ChatAdmin(
                        id=user.id,
                        first_name=user.first_name or "",
                        last_name=user.last_name,
                        username=user.username,
                        can_promote=bool(privileges and privileges.can_promote_members),
                    )
                )

        return admins

    async def transfer_ownership(self, channel_id: int, user_id: int, password: str) -> None:
        with telegram_errors():
            try:
                await self.client.transfer_chat_ownership(channel_id, user_id, password)

            # Telegram's IDs as the messages: the UI tells a refusal by them in the failed decisions
            except errors.PasswordHashInvalid as exc:
                raise InvalidPasswordError(exc.ID) from exc

            except errors.PasswordMissing as exc:
                raise PasswordMissingError(exc.ID) from exc

            except (errors.PasswordTooFresh, errors.SessionTooFresh) as exc:
                raise TooFreshError(exc.ID or "TOO_FRESH", int(exc.value or 0)) from exc

            # Kurigram's own check: the chat is no channel or the user no user
            except ValueError as exc:
                raise RequestRefusedError(str(exc)) from exc

    async def delete_chat(self, channel_id: int) -> None:
        with telegram_errors():
            try:
                # Supergroups too: both are channels.deleteChannel
                await self.client.delete_channel(channel_id)

            except errors.ChannelTooLarge as exc:
                raise ChatTooLargeError(exc.ID) from exc

    async def free_link(self, channel_id: int) -> None:
        with telegram_errors():
            await self.client.set_chat_username(channel_id, None)
