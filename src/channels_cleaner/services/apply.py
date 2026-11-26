from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from channels_cleaner.api.errors import ApplyJobRunning
from channels_cleaner.config import Settings
from channels_cleaner.database import DAO, DatabaseManager, utc_now
from channels_cleaner.enums import (
    LEAVING_ACTIONS,
    ApplyStatus,
    ChatRole,
    Decision,
    DecisionStatus,
    ItemErrorCode,
    ItemStatus,
    JobStatus,
)
from channels_cleaner.events import EventBus
from channels_cleaner.telegram import (
    ChatTooLargeError,
    FloodWaitError,
    GatewayError,
    InvalidPasswordError,
    PasswordMissingError,
    TelegramGateway,
    TooFreshError,
)

log = logging.getLogger(__name__)

APPLY_TOPIC = "apply"


MAX_FLOOD_RETRIES = 5

#: Telegram's refusals of an owner's action the UI explains in its own words
ERROR_CODES: dict[type[GatewayError], ItemErrorCode] = {
    InvalidPasswordError: "password_invalid",
    PasswordMissingError: "password_missing",
    TooFreshError: "too_fresh",
    ChatTooLargeError: "too_large",
}


@dataclass(slots=True)
class ApplyItem:
    channel_id: int
    decision: Decision
    title: str
    has_photo: bool
    status: ItemStatus = "queued"
    error: str | None = None
    reverts: Decision | None = None
    role: ChatRole = ChatRole.MEMBER
    successor_id: int | None = None
    successor_name: str | None = None
    error_code: ItemErrorCode | None = None
    retry_after: int | None = None
    #: the transfer itself went through, only the leave is left (a retry must not transfer again)
    transferred: bool = False


@dataclass(slots=True)
class ApplyState:
    job_id: int | None = None
    status: ApplyStatus = "idle"
    total: int = 0
    done: int = 0
    failed: int = 0
    current: int | None = None
    flood_wait_until: float | None = None
    items: list[ApplyItem] = field(default_factory=list)
    held_transfers: int = 0
    held_deletions: int = 0

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


class ApplyService:
    def __init__(self, gateway: TelegramGateway, database: DatabaseManager, bus: EventBus, settings: Settings) -> None:
        self.gateway = gateway
        self.database = database
        self.bus = bus
        self.settings = settings
        self.state = ApplyState()
        self.task: asyncio.Task[None] | None = None
        self.cancel_requested = asyncio.Event()
        # Held from the check to the task's creation: a second start in between would run the same queue twice
        self.starting = asyncio.Lock()
        self.rng = random.Random()  # noqa: S311 - pause jitter, not cryptography
        # The cloud password for the transfers of the running job: never stored, never logged, dropped at its end
        self.password: str | None = None
        # Once Telegram refuses the password (wrong, missing, too fresh), the other transfers would only get the same
        # answer: the item that got it, copied onto the rest without asking Telegram again
        self.transfer_refusal: ApplyItem | None = None

    @property
    def running(self) -> bool:
        return self.starting.locked() or (self.task is not None and not self.task.done())

    async def start(
        self, account_id: int, *, password: str | None = None, confirm_deletions: bool = False
    ) -> ApplyState:
        if self.running:
            raise ApplyJobRunning

        async with self.starting:
            return await self.start_job(account_id, password=password, confirm_deletions=confirm_deletions)

    async def start_job(self, account_id: int, *, password: str | None, confirm_deletions: bool) -> ApplyState:
        async with self.database.session() as session:
            dao = DAO(session)
            queued = [
                (channel, channel.decision)
                for channel in await dao.list_decided(account_id, status=DecisionStatus.PENDING)
                if channel.decision is not None
            ]
            # Without the password or the confirmation these stay in the queue, untouched, for a later run
            held_transfers = sum(1 for _, d in queued if d.decision is Decision.TRANSFER and not password)
            held_deletions = sum(1 for _, d in queued if d.decision is Decision.DELETE and not confirm_deletions)
            pending = [
                (channel, decision)
                for channel, decision in queued
                if not (decision.decision is Decision.TRANSFER and not password)
                and not (decision.decision is Decision.DELETE and not confirm_deletions)
            ]

            if not pending:
                self.state = ApplyState(status="finished", held_transfers=held_transfers, held_deletions=held_deletions)
                return self.state

            job = await dao.create_job(account_id, len(pending), utc_now())
            await dao.commit()

        self.state = ApplyState(
            job_id=job.id,
            status="running",
            total=len(pending),
            items=[
                ApplyItem(
                    channel_id=channel.channel_id,
                    decision=decision.decision,
                    title=channel.title,
                    has_photo=channel.photo_file_id is not None,
                    reverts=decision.reverts,
                    role=channel.role,
                    successor_id=decision.successor_id,
                    successor_name=decision.successor_name,
                )
                for channel, decision in pending
            ],
            held_transfers=held_transfers,
            held_deletions=held_deletions,
        )
        self.password = password
        self.transfer_refusal = None
        self.cancel_requested.clear()
        self.bus.publish(APPLY_TOPIC, "started", **self.state.snapshot())
        self.task = asyncio.create_task(self.run(account_id), name="apply-job")
        return self.state

    def cancel(self) -> None:
        self.cancel_requested.set()

    async def stop(self) -> None:
        self.cancel_requested.set()

        if self.task is not None:
            self.task.cancel()

            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task

    async def sleep(self, seconds: float) -> bool:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.cancel_requested.wait(), timeout=seconds)

        return self.cancel_requested.is_set()

    async def execute(self, item: ApplyItem) -> None:
        leaving = item.decision in LEAVING_ACTIONS

        # Leaving makes any earlier mute/archive moot; otherwise take it back first.
        if item.reverts and not leaving:
            undo = {Decision.MUTE: self.gateway.unmute, Decision.ARCHIVE: self.gateway.unarchive}[item.reverts]
            await undo(item.channel_id)

        if item.decision is Decision.TRANSFER:
            await self.transfer(item)
            return

        action = {
            Decision.UNSUBSCRIBE: self.gateway.leave,
            Decision.MUTE: self.gateway.mute,
            Decision.ARCHIVE: self.gateway.archive,
            Decision.DELETE: self.gateway.delete_chat,
            Decision.FREE_LINK: self.gateway.free_link,
        }.get(item.decision)

        if action is not None:
            await action(item.channel_id)

    async def transfer(self, item: ApplyItem) -> None:
        """Hands the chat to its successor, then leaves it; a failed leave is retried without transferring again."""
        if not item.transferred:
            if self.password is None or item.successor_id is None:
                msg = "No password or successor for the transfer"
                raise GatewayError(msg)

            await self.gateway.transfer_ownership(item.channel_id, item.successor_id, self.password)
            item.transferred = True

        await self.gateway.leave(item.channel_id)

    async def run(self, account_id: int) -> None:
        state = self.state
        job_id = state.job_id

        if job_id is None:
            msg = "The apply job has no id"
            raise RuntimeError(msg)

        try:
            for index, item in enumerate(state.items):
                if self.cancel_requested.is_set():
                    break

                state.current = item.channel_id
                item.status = "running"
                self.bus.publish(APPLY_TOPIC, "item_started", channel_id=item.channel_id, index=index)

                # The pause between actions happens while the item is already "running", so
                # the UI shows the card being worked on rather than idling, then leaving.
                if index > 0:
                    delay = self.rng.uniform(self.settings.apply_delay_min, self.settings.apply_delay_max)

                    if await self.sleep(delay):
                        break

                self.report(item, await self.apply_one(account_id, item))
                await self.save_job(job_id)

            state.current = None
            state.status = "cancelled" if self.cancel_requested.is_set() else "finished"

        except Exception:
            log.exception("Apply job crashed")
            state.status = "error"

        finally:
            self.password = None

            for item in state.items:
                if item.status == "running":
                    item.status = "queued"

            await self.save_job(job_id, finished=True)
            self.bus.publish(APPLY_TOPIC, "finished", **state.snapshot())

    async def save_job(self, job_id: int, *, finished: bool = False) -> None:
        state = self.state

        async with self.database.session() as session:
            dao = DAO(session)
            await dao.update_job(
                job_id,
                done=state.done,
                failed=state.failed,
                status=JobStatus(state.status) if finished else None,
                finished_at=utc_now() if finished else None,
            )
            await dao.commit()

    async def record(self, account_id: int, item: ApplyItem) -> None:
        async with self.database.session() as session:
            dao = DAO(session)
            now = utc_now()

            if item.status == "failed":
                if item.transferred:
                    # The chat is the successor's now, the user one of its admins: only the leave is left to retry
                    await dao.mark_transferred(account_id, item.channel_id, item.error or "")
                    await dao.set_channel_role(account_id, item.channel_id, ChatRole.ADMIN)

                else:
                    await dao.mark_decision(
                        account_id,
                        item.channel_id,
                        DecisionStatus.FAILED,
                        expected=item.decision,
                        error=item.error,
                        now=now,
                    )

                await dao.commit()
                return

            await dao.mark_decision(
                account_id, item.channel_id, DecisionStatus.APPLIED, expected=item.decision, now=now
            )

            if item.decision in LEAVING_ACTIONS:
                await dao.set_channel_gone(account_id, item.channel_id)

            elif item.decision is Decision.FREE_LINK:
                await dao.set_channel_username(account_id, item.channel_id, None)

            else:
                # The mute or archive taken back is off now, the decision's own one is on
                flags: dict[Decision, bool] = {}

                if item.reverts is not None:
                    flags[item.reverts] = False

                if item.decision in {Decision.MUTE, Decision.ARCHIVE}:
                    flags[item.decision] = True

                if flags:
                    await dao.set_channel_flags(
                        account_id,
                        item.channel_id,
                        muted=flags.get(Decision.MUTE),
                        archived=flags.get(Decision.ARCHIVE),
                    )

            await dao.commit()

    def report(self, item: ApplyItem, result: ItemStatus) -> None:
        state = self.state

        if result == "done":
            state.done += 1
            self.bus.publish(APPLY_TOPIC, "item_done", channel_id=item.channel_id, done=state.done, failed=state.failed)

        elif result == "failed":
            state.failed += 1
            self.bus.publish(
                APPLY_TOPIC,
                "item_failed",
                channel_id=item.channel_id,
                error=item.error,
                done=state.done,
                failed=state.failed,
            )

    async def still_wanted(self, account_id: int, item: ApplyItem) -> bool:
        """Whether the decision is still the one queued: edits are refused while applying, this is the last guard."""
        async with self.database.session() as session:
            current = await DAO(session).get_decision(account_id, item.channel_id)

        return (
            current is not None
            and current.status is DecisionStatus.PENDING
            and current.decision is item.decision
            and current.reverts is item.reverts
        )

    async def apply_one(self, account_id: int, item: ApplyItem) -> ItemStatus:
        if not await self.still_wanted(account_id, item):
            # Nothing done in Telegram, nothing written: the decision in the database is someone else's now
            item.status = "failed"
            item.error = "The decision changed while applying"
            return item.status

        refusal = self.transfer_refusal

        if item.decision is Decision.TRANSFER and refusal is not None:
            item.status = "failed"
            item.error, item.error_code, item.retry_after = refusal.error, refusal.error_code, refusal.retry_after
            await self.record(account_id, item)
            return item.status

        for _ in range(MAX_FLOOD_RETRIES + 1):
            try:
                await self.execute(item)

            except FloodWaitError as exc:
                wait = exc.seconds + 1
                self.state.flood_wait_until = time.time() + wait
                self.bus.publish(
                    APPLY_TOPIC,
                    "flood_wait",
                    channel_id=item.channel_id,
                    seconds=wait,
                    until=self.state.flood_wait_until,
                )
                cancelled = await self.sleep(wait)
                self.state.flood_wait_until = None
                self.bus.publish(APPLY_TOPIC, "flood_wait_over", channel_id=item.channel_id)

                if cancelled:
                    item.status = "queued"
                    return item.status

                continue

            except GatewayError as exc:
                item.status = "failed"
                item.error = str(exc) or type(exc).__name__
                item.error_code = ERROR_CODES.get(type(exc))
                item.retry_after = exc.seconds if isinstance(exc, TooFreshError) else None

                if item.decision is Decision.TRANSFER and not item.transferred and item.error_code is not None:
                    self.transfer_refusal = item

                await self.record(account_id, item)
                return item.status

            item.status = "done"
            await self.record(account_id, item)
            return item.status

        item.status = "failed"
        item.error = "Too many flood waits"
        await self.record(account_id, item)
        return item.status
