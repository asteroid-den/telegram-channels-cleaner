from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from channels_cleaner.config import Settings
from channels_cleaner.enums import ChatKind, ChatRole, MediaKind
from channels_cleaner.telegram.device_profiles import DeviceProfile, all_profiles
from channels_cleaner.telegram.types import (
    DELETE_LIMIT,
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
    PasswordNeededError,
    QrToken,
    RequestRefusedError,
    TgUser,
)

MOCK_CODE = "12345"
MOCK_PASSWORD = "mock"
MOCK_USER = TgUser(id=777000111, first_name="Mock", last_name="User", username="mock_user")
#: who logs in to each further mock session, in turn
MOCK_USERS = (
    MOCK_USER,
    TgUser(id=777000222, first_name="Work", last_name="Mock", username="mock_work"),
    TgUser(id=777000333, first_name="Side", last_name="Project", username=None),
)

ADJECTIVES = [
    "Daily",
    "Crypto",
    "Tech",
    "Rust",
    "Python",
    "Frontend",
    "Indie",
    "Retro",
    "Quiet",
    "Night",
    "Urban",
    "Data",
    "Design",
    "Linux",
    "Space",
    "Coffee",
    "Vinyl",
    "Pixel",
]
NOUNS = [
    "Digest",
    "News",
    "Notes",
    "Memes",
    "Insights",
    "Weekly",
    "Radar",
    "Lab",
    "Corner",
    "Chronicles",
    "Feed",
    "Club",
    "Journal",
    "Signals",
    "Drops",
    "Hub",
]
RU_TITLES = [
    "Заметки разработчика",
    "Новости за минуту",
    "Тихий канал",
    "Кофе и код",
    "Ночной эфир",
    "Типичный бэкендер",
    "Мемы про деплой",
    "Вечерний дайджест",
    "Книжная полка",
    "Кино без спойлеров",
    "Путешествия налегке",
    "Сад и огород",
    "Финансы просто",
]
TEXTS = [
    "Big update today: we shipped the thing everyone has been asking for. Details inside 👇",
    "Короткий пост о том, почему не стоит деплоить в пятницу вечером.",
    "Weekly roundup: 7 links worth your attention this week.",
    "Розыгрыш! Подпишись на три канала партнёров и получи шанс выиграть ничего.",
    "Thread: how we cut our cloud bill in half without rewriting anything.",
    "Сегодня без лонгрида — просто красивая фотография заката.",
    "Reminder: the meetup starts in an hour, stream link in the pinned message.",
    "Мы переезжаем! Новый канал по ссылке, этот скоро будет удалён.",
]
ABOUTS = [
    "Everything about modern backend development. No ads, no spam.",
    "Авторский канал о технологиях, жизни и всём остальном. По рекламе — в личку.",
    "Curated links, once a day. Sometimes twice.",
    "Канал, который вы забыли, что читаете.",
    None,
]
GROUP_NOUNS = ["Chat", "Talk", "Club", "Community", "Help", "Offtopic", "Flood", "Meetup"]
GROUP_RU_TITLES = [
    "Чат разработчиков",
    "Барахолка района",
    "Соседи из 3-го подъезда",
    "Флудилка",
    "Вопросы по Python",
    "Клуб любителей кофе",
    "Помощь с ремонтом",
    "Книжный клуб",
]
GROUP_TEXTS = [
    "Кто-нибудь сталкивался с такой ошибкой? Скину лог в ветку.",
    "Anyone up for a call tomorrow evening?",
    "Спасибо, помогло! Закрываю вопрос.",
    "lol, same here",
    "Ребят, продаю монитор, подробности в личке.",
    "Does anyone know a good tutorial for this?",
    "+1, тоже интересно",
    "Reminder: please keep it on topic.",
]
MEDIA: list[MediaKind | None] = [
    None,
    None,
    None,
    MediaKind.PHOTO,
    MediaKind.PHOTO,
    MediaKind.VIDEO,
    MediaKind.DOCUMENT,
    MediaKind.POLL,
]
ADMIN_NAMES = [
    ("Anna", "Petrova", "anna_p"),
    ("Max", None, "maxwell"),
    ("Ilya", "Sokolov", None),
    ("Kate", "Moss", "kate_m"),
    ("Oleg", None, None),
    ("Sam", "Lee", "samlee"),
    ("Dasha", "K.", "dashak"),
]
COLORS = ["#e17076", "#7bc862", "#e5ca77", "#65aadd", "#a695e7", "#ee7aae", "#6ec9cb", "#faa774"]


ID_BASE: dict[ChatKind, int] = {ChatKind.CHANNEL: -1001000000000, ChatKind.SUPERGROUP: -1002000000000}


def generate_chat(
    count: int, seed: int = 42, kind: ChatKind = ChatKind.CHANNEL
) -> dict[int, tuple[ChannelInfo, ChannelFull]]:
    rng = random.Random(seed if kind is ChatKind.CHANNEL else seed + 1000)
    now = datetime.now(UTC)
    channels: dict[int, tuple[ChannelInfo, ChannelFull]] = {}
    group = kind is ChatKind.SUPERGROUP
    texts = GROUP_TEXTS if group else TEXTS

    for i in range(count):
        channel_id = ID_BASE[kind] - i

        # The same draws as always, in the same order: the mock's chats keep their names
        russian = rng.random() < 0.3

        if group:
            title = rng.choice(GROUP_RU_TITLES) if russian else f"{rng.choice(ADJECTIVES)} {rng.choice(GROUP_NOUNS)}"

        else:
            title = rng.choice(RU_TITLES) if russian else f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"

        if any(info.title == title for info, _ in channels.values()):
            title = f"{title} #{i}"

        # Skewed activity: lots of fresh channels, a long tail of dead ones, some never posted.
        roll = rng.random()

        if roll < 0.04:
            last_post_at = None

        elif roll < 0.5:
            last_post_at = now - timedelta(hours=rng.uniform(0.2, 24 * 7))

        else:
            last_post_at = now - timedelta(days=rng.expovariate(1 / 160) + 7)

        unread = 0 if rng.random() < 0.25 else int(rng.expovariate(1 / 120))
        media = rng.choice(MEDIA) if last_post_at else None
        members = int(rng.lognormvariate(8, 1.6))
        # its own generator, so the roles don't shift what everything else is generated from
        role_roll = random.Random(f"{seed}/{kind}/{i}").random()
        role = ChatRole.OWNER if role_roll < 0.04 else ChatRole.ADMIN if role_roll < 0.11 else ChatRole.MEMBER
        info = ChannelInfo(
            id=channel_id,
            title=title,
            username=None if rng.random() < 0.15 else f"mock_{kind[:1]}{i:03d}",
            unread_count=unread,
            is_muted=rng.random() < 0.3,
            is_archived=rng.random() < 0.15,
            members_count=members if rng.random() < 0.5 else None,
            photo_file_id=None if rng.random() < 0.1 else f"mock-photo-{i}",
            photo_unique_id=None if rng.random() < 0.1 else f"u{i}",
            last_post_id=rng.randint(10, 9000) if last_post_at else None,
            last_post_at=last_post_at,
            last_post_text=rng.choice(texts) if last_post_at and rng.random() < 0.9 else None,
            last_post_media=media,
            kind=kind,
            role=role,
        )

        if info.photo_file_id is None:
            info = replace(info, photo_unique_id=None)

        full = ChannelFull(about=rng.choice(ABOUTS), members_count=members)
        channels[channel_id] = (info, full)

    return channels


def initials(title: str) -> str:
    words = [w for w in title.replace("#", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def avatar_svg(title: str, color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        f'<rect width="160" height="160" fill="{color}"/>'
        '<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
        'font-family="system-ui, sans-serif" font-size="64" font-weight="600" fill="#fff">'
        f"{escape(initials(title))}</text></svg>"
    )


def portrait_svg(color: str) -> str:
    """A head and shoulders on a gradient: a stand-in photo that looks unlike the initials fallback."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        f'<defs><linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="{color}"/>'
        '<stop offset="1" stop-color="#1e2027"/></linearGradient></defs>'
        '<rect width="160" height="160" fill="url(#g)"/>'
        '<circle cx="80" cy="64" r="28" fill="#f1d3b6"/>'
        '<path d="M28 160c4-34 26-52 52-52s48 18 52 52z" fill="#2e313b"/></svg>'
    )


def thumb_svg(seed: int) -> str:
    rng = random.Random(seed)
    a, b = rng.sample(COLORS, 2)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{a}"/>'
        f'<stop offset="1" stop-color="{b}"/></linearGradient></defs>'
        '<rect width="320" height="200" fill="url(#g)"/>'
        f'<circle cx="{rng.randint(60, 260)}" cy="{rng.randint(40, 160)}" '
        f'r="{rng.randint(20, 60)}" '
        'fill="#fff" fill-opacity=".25"/></svg>'
    )


def generate_admins(channel_id: int) -> list[ChatAdmin]:
    """A few admins per chat, none in about a quarter of them; the same ones every time."""
    rng = random.Random(f"admins/{channel_id}")
    count = 0 if rng.random() < 0.25 else rng.randint(1, 4)
    return [
        ChatAdmin(
            id=900_000_000 + abs(channel_id) % 100_000 * 10 + index,
            first_name=first,
            last_name=last,
            username=username,
            can_promote=index == 0 or rng.random() < 0.3,
        )
        for index, (first, last, username) in enumerate(rng.sample(ADMIN_NAMES, count))
    ]


class MockGateway:
    """Actions occasionally raise flood waits and errors, so the UI paths for them can be tried."""

    qr_scan_after: float = 4.0

    def __init__(self, settings: Settings, *, seed: int = 42) -> None:
        self.settings = settings
        self.seed = seed
        self.session = LEGACY_SESSION
        self.channels = self.generate_all(seed)
        self.authorized = False
        self.user: TgUser | None = None
        self.awaiting_password = False
        self.phone: str | None = None
        self.qr_round = 0
        self.rng = random.Random(seed + 1)
        self._profile = all_profiles()[0]
        self.action_delay = 0.15

    def generate_all(self, seed: int) -> dict[int, tuple[ChannelInfo, ChannelFull]]:
        return {
            **generate_chat(self.settings.mock_channels, seed),
            **generate_chat(self.settings.mock_supergroups, seed, ChatKind.SUPERGROUP),
        }

    @property
    def device_profile(self) -> DeviceProfile | None:
        return self._profile

    def state_file(self, session: str) -> Path:
        # The file of the versions with one account stays where it was
        name = "mock_session.json" if session == LEGACY_SESSION else f"mock_{session}.json"
        return self.settings.data_dir / name

    @property
    def state_path(self) -> Path:
        return self.state_file(self.session)

    def channels_of(self, user: TgUser | None) -> dict[int, tuple[ChannelInfo, ChannelFull]]:
        # Every mock account has chats of its own; the first one keeps the ones it always had
        return self.generate_all(self.seed if user is None or user.id == MOCK_USER.id else user.id % 1000)

    async def start(self, session: str) -> TgUser | None:
        self.session = session
        self.authorized = False
        self.user = None
        self.awaiting_password = False
        self.phone = None
        state = json.loads(self.state_path.read_text("utf-8")) if self.state_path.exists() else {}

        if state.get("authorized"):
            self.authorized = True
            self.user = TgUser(**state["user"]) if "user" in state else MOCK_USER

        gone = set(state.get("gone", []))
        self.channels = {k: v for k, v in self.channels_of(self.user).items() if k not in gone}
        return self.user

    async def stop(self) -> None:
        return None

    def save_state(self, gone: set[int] | None = None) -> None:
        user = asdict(self.user) if self.user is not None else None
        state = {"authorized": self.authorized, "user": user, "gone": sorted(gone or set())}

        if self.state_path.exists() and gone is None:
            state["gone"] = json.loads(self.state_path.read_text("utf-8")).get("gone", [])

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state), "utf-8")

    def authorize(self) -> TgUser:
        if self.settings.mock_2fa:
            self.awaiting_password = True
            raise PasswordNeededError

        return self.log_in()

    def log_in(self) -> TgUser:
        taken = {self.user_of(path) for path in self.settings.data_dir.glob("mock_*.json") if path != self.state_path}
        self.user = next((user for user in MOCK_USERS if user.id not in taken), MOCK_USERS[-1])
        self.authorized = True
        self.channels = self.channels_of(self.user)
        self.save_state()
        return self.user

    @staticmethod
    def user_of(path: Path) -> int | None:
        state = json.loads(path.read_text("utf-8"))
        return (state.get("user") or {}).get("id", MOCK_USER.id) if state.get("authorized") else None

    def require_auth(self) -> None:
        if not self.authorized:
            msg = "Not authorized"
            raise NotAuthorizedError(msg)

    async def qr_export(self) -> QrToken:
        if self.authorized:
            msg = "Already authorized"
            raise GatewayError(msg)

        self.qr_round += 1
        return QrToken(
            url=f"tg://login?token=mock-{self.qr_round}",
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
        )

    async def qr_wait(self) -> TgUser:
        await asyncio.sleep(self.qr_scan_after)
        return self.authorize()

    async def send_code(self, phone: str) -> None:
        digits = "".join(ch for ch in phone if ch.isdigit())

        if len(digits) < 7:
            msg = "PHONE_NUMBER_INVALID"
            raise InvalidPhoneError(msg)

        self.phone = phone

    async def sign_in_code(self, code: str) -> TgUser:
        if not self.phone:
            msg = "Request a code first"
            raise GatewayError(msg)

        if code.strip() != MOCK_CODE:
            msg = "PHONE_CODE_INVALID"
            raise InvalidCodeError(msg)

        return self.authorize()

    async def password_hint(self) -> str | None:
        return "it's literally 'mock'"

    async def check_password(self, password: str) -> TgUser:
        if not self.awaiting_password:
            msg = "Password is not expected now"
            raise GatewayError(msg)

        if password != MOCK_PASSWORD:
            msg = "PASSWORD_HASH_INVALID"
            raise InvalidPasswordError(msg)

        self.awaiting_password = False
        return self.log_in()

    async def log_out(self) -> None:
        await self.forget_session()

    async def forget_session(self) -> None:
        self.authorized = False
        self.user = None
        self.state_path.unlink(missing_ok=True)
        self.channels = self.channels_of(None)

    async def iter_channels(self) -> AsyncIterator[ChannelInfo]:
        self.require_auth()

        for index, (info, _) in enumerate(list(self.channels.values())):
            if index % 25 == 0:
                await asyncio.sleep(0.05)  # pretend to paginate

            yield info

    async def get_full(self, channel_id: int) -> ChannelFull:
        self.require_auth()
        await asyncio.sleep(0.15)
        entry = self.channels.get(channel_id)

        if entry is None:
            msg = "CHANNEL_INVALID"
            raise RequestRefusedError(msg)

        return entry[1]

    async def recent_post_dates(self, channel_id: int, limit: int) -> list[datetime]:
        self.require_auth()
        entry = self.channels.get(channel_id)
        last = entry[0].last_post_at if entry is not None else None

        if last is None:
            return []

        rng = random.Random(channel_id)
        # A posting rate that matches how "alive" the channel looks; dead channels get a
        # slower rate so their pulse visibly fades out into the past.
        quiet_days = (datetime.now(UTC) - last).days
        rate = rng.choice([0.3, 0.8, 1.5, 3, 8]) if quiet_days < 14 else rng.choice([0.2, 0.5, 1])
        dates = [last]
        current = last

        while len(dates) < limit:
            current -= timedelta(days=rng.expovariate(rate) + 0.01)

            if (last - current).days > 400:
                break

            dates.append(current)

        return dates

    async def download_avatar(self, channel_id: int, file_id: str, dest: Path) -> Path | None:  # noqa: ARG002 - draws its own
        entry = self.channels.get(channel_id)

        if entry is None:
            return None

        path = dest.with_suffix(".svg")
        color = COLORS[abs(channel_id) % len(COLORS)]
        path.write_text(avatar_svg(entry[0].title, color), "utf-8")
        return path

    async def download_own_photo(self, dest: Path) -> Path | None:
        self.require_auth()

        # The last mock user has no photo, so the initials fallback can be seen too
        if self.user is None or self.user.id == MOCK_USERS[-1].id:
            return None

        path = dest.with_suffix(".svg")
        path.write_text(portrait_svg(COLORS[self.user.id % len(COLORS)]), "utf-8")
        return path

    async def download_post_thumb(self, channel_id: int, message_id: int, dest: Path) -> Path | None:
        entry = self.channels.get(channel_id)

        if entry is None or entry[0].last_post_media not in {MediaKind.PHOTO, MediaKind.VIDEO}:
            return None

        path = dest.with_suffix(".svg")
        path.write_text(thumb_svg(channel_id + message_id), "utf-8")
        return path

    async def maybe_fail(self) -> None:
        await asyncio.sleep(self.action_delay)
        roll = self.rng.random()

        if roll < 0.05:
            raise FloodWaitError(self.rng.randint(3, 6))

        if roll < 0.08:
            msg = "CHANNEL_PRIVATE"
            raise GatewayError(msg)

    async def leave(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()
        self.drop(channel_id)

    def drop(self, channel_id: int) -> None:
        self.channels.pop(channel_id, None)
        gone: set[int] = set()

        if self.state_path.exists():
            gone = set(json.loads(self.state_path.read_text("utf-8")).get("gone", []))

        gone.add(channel_id)
        self.save_state(gone)

    async def mute(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()

        if channel_id in self.channels:
            info, full = self.channels[channel_id]
            self.channels[channel_id] = (replace(info, is_muted=True), full)

    async def archive(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()

        if channel_id in self.channels:
            info, full = self.channels[channel_id]
            self.channels[channel_id] = (replace(info, is_archived=True), full)

    async def unmute(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()

        if channel_id in self.channels:
            info, full = self.channels[channel_id]
            self.channels[channel_id] = (replace(info, is_muted=False), full)

    async def unarchive(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()

        if channel_id in self.channels:
            info, full = self.channels[channel_id]
            self.channels[channel_id] = (replace(info, is_archived=False), full)

    def update_info(self, channel_id: int, **changes: object) -> None:
        if channel_id in self.channels:
            info, full = self.channels[channel_id]
            self.channels[channel_id] = (replace(info, **changes), full)  # pyright: ignore[reportArgumentType] - ChannelInfo fields

    def owned(self, channel_id: int) -> tuple[ChannelInfo, ChannelFull]:
        entry = self.channels.get(channel_id)

        if entry is None or entry[0].role is not ChatRole.OWNER:
            msg = "CHAT_ADMIN_REQUIRED"
            raise RequestRefusedError(msg)

        return entry

    async def get_admins(self, channel_id: int) -> list[ChatAdmin]:
        self.require_auth()
        await asyncio.sleep(self.action_delay)

        if channel_id not in self.channels:
            msg = "CHANNEL_INVALID"
            raise RequestRefusedError(msg)

        return generate_admins(channel_id)

    async def transfer_ownership(self, channel_id: int, user_id: int, password: str) -> None:
        self.require_auth()
        await asyncio.sleep(self.action_delay)
        self.owned(channel_id)

        # Every mock account has a cloud password for this, whatever CC_MOCK_2FA says about the login
        if password != MOCK_PASSWORD:
            msg = "PASSWORD_HASH_INVALID"
            raise InvalidPasswordError(msg)

        if user_id not in {admin.id for admin in generate_admins(channel_id)}:
            msg = "USER_ID_INVALID"
            raise RequestRefusedError(msg)

        # The old owner stays on as an admin
        self.update_info(channel_id, role=ChatRole.ADMIN)

    async def delete_chat(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()
        _, full = self.owned(channel_id)

        if (full.members_count or 0) > DELETE_LIMIT:
            msg = "CHANNEL_TOO_LARGE"
            raise ChatTooLargeError(msg)

        self.drop(channel_id)

    async def free_link(self, channel_id: int) -> None:
        self.require_auth()
        await self.maybe_fail()
        self.owned(channel_id)
        self.update_info(channel_id, username=None)
