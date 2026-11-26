from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from channels_cleaner.config import Settings
from channels_cleaner.context import AppContext
from channels_cleaner.enums import ChatRole, Decision, DecisionStatus
from channels_cleaner.telegram import DELETE_LIMIT, GatewayError, MockGateway, TooFreshError, mock_gateway
from channels_cleaner.telegram.mock_gateway import MOCK_PASSWORD, generate_admins
from tests.conftest import get_json, login, open_dao, wait_for


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Enough chats for owned ones of every sort: with admins and without, public and private, small and large
    return Settings(
        data_dir=tmp_path,
        mock=True,
        mock_channels=300,
        mock_supergroups=0,
        apply_delay_min=0,
        apply_delay_max=0.01,
        _env_file=None,  # pyright: ignore[reportCallIssue] - pydantic-settings init option, not a field
    )


@pytest.fixture
def gateway(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> MockGateway:
    gw = MockGateway(settings)
    gw.qr_scan_after = 0.05
    gw.action_delay = 0

    # No random flood waits or refusals: these tests are about what Telegram says on purpose
    async def never() -> None:
        return None

    monkeypatch.setattr(gw, "maybe_fail", never)
    return gw


async def owned(client: httpx.AsyncClient, gateway: MockGateway, where: Callable[[int], bool]) -> list[int]:
    items = (await get_json(client, "/api/channels", params={"role": "managed", "state": "all"}))["items"]
    return [item["id"] for item in items if item["role"] == "owner" and where(item["id"])]


def members(gateway: MockGateway, channel_id: int) -> int:
    return gateway.channels[channel_id][1].members_count or 0


def with_admins(gateway: MockGateway) -> Callable[[int], bool]:
    return lambda cid: bool(generate_admins(cid)) and members(gateway, cid) > 0


async def decide(client: httpx.AsyncClient, channel_id: int, decision: str, **extra: Any) -> httpx.Response:  # noqa: ANN401
    return await client.put(f"/api/decisions/{channel_id}", json={"decision": decision, **extra})


async def transfer(client: httpx.AsyncClient, channel_id: int) -> None:
    successor = generate_admins(channel_id)[0].id
    r = await decide(client, channel_id, "transfer", successor_id=successor)
    assert r.status_code == 200, r.text


async def apply(client: httpx.AsyncClient, ctx: AppContext, **body: Any) -> dict[str, Any]:  # noqa: ANN401
    r = await client.post("/api/apply", json=body)
    assert r.status_code == 200, r.text

    async def finished() -> bool:
        return not ctx.apply.running

    await wait_for(finished)
    return await get_json(client, "/api/apply/state")


async def decision_of(ctx: AppContext, channel_id: int) -> tuple[Decision, DecisionStatus] | None:
    async with open_dao(ctx) as dao:
        row = await dao.get_decision(ctx.auth.account_id, channel_id)

    return (row.decision, row.status) if row is not None else None


async def test_an_owned_chat_lists_its_admins(client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway) -> None:
    await login(client, ctx)
    chat = (await owned(client, gateway, with_admins(gateway)))[0]

    items = (await get_json(client, f"/api/channels/{chat}/admins"))["items"]

    assert [item["id"] for item in items] == [admin.id for admin in generate_admins(chat)]
    assert {"first_name", "last_name", "username", "can_promote"} <= items[0].keys()


async def test_only_the_owner_gets_the_admins_and_the_owner_actions(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    member = (await get_json(client, "/api/channels"))["items"][0]["id"]

    r = await client.get(f"/api/channels/{member}/admins")

    assert (r.status_code, r.json()["type"]) == (409, "not_chat_owner")

    for decision in ("delete", "free_link"):
        r = await decide(client, member, decision)
        assert (r.status_code, r.json()["type"]) == (409, "not_chat_owner")


async def test_a_transfer_needs_one_of_the_admins(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway
) -> None:
    await login(client, ctx)
    chat = (await owned(client, gateway, with_admins(gateway)))[0]
    admin = generate_admins(chat)[0]

    assert (await decide(client, chat, "transfer")).status_code == 422
    assert (await decide(client, chat, "keep", successor_id=admin.id)).status_code == 422
    r = await decide(client, chat, "transfer", successor_id=42)
    assert (r.status_code, r.json()["type"]) == (409, "successor_not_admin")

    assert (await decide(client, chat, "transfer", successor_id=admin.id)).status_code == 200
    items = (await get_json(client, "/api/decisions", params={"status": "pending"}))["items"]
    assert [(i["id"], i["successor_id"], i["successor_name"]) for i in items] == [
        (chat, admin.id, f"{admin.first_name} {admin.last_name or ''}".strip())
    ]


async def test_telegram_limits_are_checked_when_deciding(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway
) -> None:
    await login(client, ctx)
    large = (await owned(client, gateway, lambda cid: members(gateway, cid) > DELETE_LIMIT))[0]
    private = await owned(client, gateway, lambda cid: gateway.channels[cid][0].username is None)
    await get_json(client, f"/api/channels/{large}/full")  # the size comes with the full info

    r = await decide(client, large, "delete")

    assert (r.status_code, r.json()["type"], r.json()["members_count"]) == (
        409,
        "chat_too_large_to_delete",
        members(gateway, large),
    )

    if private:
        r = await decide(client, private[0], "free_link")
        assert (r.status_code, r.json()["type"]) == (409, "no_public_link")


async def test_without_the_password_and_the_confirmation_those_stay_queued(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway
) -> None:
    await login(client, ctx)
    small_with_admins = await owned(
        client, gateway, lambda cid: bool(generate_admins(cid)) and 0 < members(gateway, cid) <= DELETE_LIMIT
    )
    to_transfer, to_delete, to_mute = small_with_admins[:3]
    await transfer(client, to_transfer)
    assert (await decide(client, to_delete, "delete")).status_code == 200
    assert (await decide(client, to_mute, "mute")).status_code == 200

    state = await apply(client, ctx)

    assert [item["channel_id"] for item in state["items"]] == [to_mute]
    assert (state["held_transfers"], state["held_deletions"]) == (1, 1)
    assert await decision_of(ctx, to_transfer) == (Decision.TRANSFER, DecisionStatus.PENDING)
    assert await decision_of(ctx, to_delete) == (Decision.DELETE, DecisionStatus.PENDING)
    assert to_transfer in gateway.channels
    assert to_delete in gateway.channels


async def test_a_transfer_hands_the_chat_over_then_leaves(
    client: httpx.AsyncClient,
    ctx: AppContext,
    gateway: MockGateway,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    # One that can't turn up in a log by chance
    password = "s3cret-Pa55-9431"
    monkeypatch.setattr(mock_gateway, "MOCK_PASSWORD", password)
    await login(client, ctx)
    chat = (await owned(client, gateway, with_admins(gateway)))[0]
    await transfer(client, chat)

    state = await apply(client, ctx, password=password)

    admin = generate_admins(chat)[0]
    assert [(i["status"], i["successor_name"]) for i in state["items"]] == [
        ("done", f"{admin.first_name} {admin.last_name or ''}".strip())
    ]
    assert chat not in gateway.channels
    assert await decision_of(ctx, chat) == (Decision.TRANSFER, DecisionStatus.APPLIED)
    # The password lived only as long as the job
    assert ctx.apply.password is None
    assert password not in caplog.text


async def test_a_wrong_password_fails_every_transfer_but_asks_telegram_once(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client, ctx)
    first, second = (await owned(client, gateway, with_admins(gateway)))[:2]
    await transfer(client, first)
    await transfer(client, second)
    calls: list[int] = []
    real = gateway.transfer_ownership

    async def counted(channel_id: int, user_id: int, password: str) -> None:
        calls.append(channel_id)
        await real(channel_id, user_id, password)

    monkeypatch.setattr(gateway, "transfer_ownership", counted)

    state = await apply(client, ctx, password="wrong")

    assert len(calls) == 1
    assert [(i["status"], i["error_code"]) for i in state["items"]] == [("failed", "password_invalid")] * 2
    assert {first, second} <= gateway.channels.keys()
    assert await decision_of(ctx, second) == (Decision.TRANSFER, DecisionStatus.FAILED)


async def test_a_session_too_fresh_says_how_long_to_wait(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client, ctx)
    chat = (await owned(client, gateway, with_admins(gateway)))[0]
    await transfer(client, chat)

    async def too_fresh(*_: object) -> None:
        raise TooFreshError("SESSION_TOO_FRESH_X", 61_200)

    monkeypatch.setattr(gateway, "transfer_ownership", too_fresh)

    state = await apply(client, ctx, password=MOCK_PASSWORD)

    assert [(i["error_code"], i["retry_after"]) for i in state["items"]] == [("too_fresh", 61_200)]


async def test_a_failed_leave_after_the_transfer_is_retried_as_a_plain_leave(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client, ctx)
    chat = (await owned(client, gateway, with_admins(gateway)))[0]
    await transfer(client, chat)
    real_leave = gateway.leave

    async def refused(_: int) -> None:
        msg = "CHANNEL_PRIVATE"
        raise GatewayError(msg)

    monkeypatch.setattr(gateway, "leave", refused)
    await apply(client, ctx, password=MOCK_PASSWORD)

    assert await decision_of(ctx, chat) == (Decision.UNSUBSCRIBE, DecisionStatus.FAILED)

    async with open_dao(ctx) as dao:
        row = await dao.get_channel(ctx.auth.account_id, chat)

    assert row is not None
    assert row.role is ChatRole.ADMIN

    # The retry only leaves: no password needed, nothing handed over twice
    monkeypatch.setattr(gateway, "leave", real_leave)
    assert (await client.post("/api/decisions/retry-failed", params={"role": "managed"})).status_code == 200
    state = await apply(client, ctx)

    assert [(i["decision"], i["status"]) for i in state["items"]] == [("unsubscribe", "done")]
    assert chat not in gateway.channels


async def test_a_confirmed_deletion_and_a_freed_link(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway
) -> None:
    await login(client, ctx)
    small = (await owned(client, gateway, lambda cid: 0 < members(gateway, cid) <= DELETE_LIMIT))[0]
    public = next(
        cid
        for cid in await owned(client, gateway, lambda cid: gateway.channels[cid][0].username is not None)
        if cid != small
    )
    assert (await decide(client, small, "delete")).status_code == 200
    assert (await decide(client, public, "free_link")).status_code == 200

    state = await apply(client, ctx, confirm_deletions=True)

    assert {i["status"] for i in state["items"]} == {"done"}
    assert small not in gateway.channels
    assert gateway.channels[public][0].username is None
    channel = await get_json(client, f"/api/channels/{public}/full")
    assert (channel["username"], channel["decision"], channel["decision_status"]) == (None, "free_link", "applied")
