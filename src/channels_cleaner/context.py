from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field

from channels_cleaner.api.errors import AccountNotFound, ApplyJobRunning
from channels_cleaner.config import Settings
from channels_cleaner.database import DAO, DatabaseManager, utc_now
from channels_cleaner.events import EventBus
from channels_cleaner.services import (
    SCOPE_SETTING,
    SCOPE_VERSION,
    ApplyService,
    AuthService,
    ChannelsService,
    NetworkService,
    SyncService,
)
from channels_cleaner.telegram import (
    LEGACY_SESSION,
    GatewayError,
    MockGateway,
    TelegramGateway,
    TgUser,
    new_session_name,
)

log = logging.getLogger(__name__)

RECONNECT_DELAYS = (2, 5, 10, 30, 60)


def make_gateway(settings: Settings) -> TelegramGateway:
    if settings.mock:
        return MockGateway(settings)

    # Imported here only: mock mode does not load Kurigram at all
    from channels_cleaner.telegram.kurigram_gateway import KurigramGateway  # noqa: PLC0415

    return KurigramGateway(settings)


@dataclass
class AppContext:
    settings: Settings
    database: DatabaseManager
    bus: EventBus
    gateway: TelegramGateway
    auth: AuthService
    sync: SyncService
    channels: ChannelsService
    apply: ApplyService
    network: NetworkService
    boot_task: asyncio.Task[None] | None = field(default=None, repr=False)

    @classmethod
    def create(cls, settings: Settings, gateway: TelegramGateway | None = None) -> AppContext:
        settings.ensure_dirs()
        database = DatabaseManager(settings.db_path)
        bus = EventBus()
        gw = gateway or make_gateway(settings)
        return cls(
            settings=settings,
            database=database,
            bus=bus,
            gateway=gw,
            auth=AuthService(gw, database, bus),
            sync=SyncService(gw, database, bus),
            channels=ChannelsService(gw, database, settings),
            apply=ApplyService(gw, database, bus, settings),
            network=NetworkService(database, bus, settings),
        )

    async def startup(self) -> None:
        await self.database.migrate()

        async with self.database.session() as session:
            dao = DAO(session)
            await dao.interrupt_running_jobs(utc_now())
            # "Skip" means "not now", so it lasts one launch
            await dao.clear_skips()
            await dao.commit()

        await self.network.startup()
        self.auth.on_login(self.after_login)
        self.boot_task = asyncio.create_task(self.boot(), name="boot")

    async def boot(self) -> None:
        # Started without a network (a laptop waking up, a VPN not up yet): keep trying instead of asking for a restart
        for attempt in itertools.count():
            try:
                await self.auth.start(await self.active_session())

            except Exception as exc:
                if attempt == 0:
                    log.exception("Could not connect to Telegram, retrying")

                self.auth.connect_failed(exc)
                await asyncio.sleep(RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)])

            else:
                return

    async def active_session(self) -> str:
        async with self.database.session() as session:
            stored = await DAO(session).active_session()

        # Nothing stored before the first login, or by the versions with one account: their session is the legacy one
        return stored or LEGACY_SESSION

    async def switch_account(self, account_id: int) -> None:
        async with self.database.session() as session:
            account = await DAO(session).get_account(account_id)

        if account is None or account.session_name is None:
            raise AccountNotFound(account_id=account_id)

        await self.switch_session(account.session_name)

    async def add_account(self) -> None:
        await self.switch_session(new_session_name())

    async def switch_session(self, session: str) -> None:
        # The job works for the account it started with, and stopping it halfway is the user's call
        if self.apply.running:
            raise ApplyJobRunning

        await self.sync.forget()
        self.channels.reset()
        await self.auth.switch_to(session)

    async def after_login(self, user: TgUser) -> None:
        await self.sync.load(user.id)

        async with self.database.session() as session:
            dao = DAO(session)
            empty = await dao.count_channels(user.id) == 0
            outdated = await dao.get_setting(user.id, SCOPE_SETTING) != SCOPE_VERSION

        if empty or outdated:
            self.sync.start(user.id)

        try:
            await self.channels.refresh_own_photo(user.id)

        # The one from before stays; the next login tries again
        except GatewayError as exc:
            log.warning("Could not fetch the profile photo: %s", exc)

        # Tells the UI the accounts list changed: it now has the photo
        else:
            self.auth.publish()

    async def wait_ready(self) -> None:
        if self.boot_task is not None:
            await self.boot_task

    async def shutdown(self) -> None:
        if self.boot_task is not None and not self.boot_task.done():
            self.boot_task.cancel()

        await self.network.stop()
        await self.apply.stop()
        await self.sync.stop()
        await self.auth.stop()
        await self.gateway.stop()
        await self.database.dispose()
