from __future__ import annotations

import httpx
import pytest

from channels_cleaner.api.models import telegram_url
from channels_cleaner.context import AppContext
from channels_cleaner.telegram import (
    ChannelFull,
    FloodWaitError,
    GatewayError,
    MockGateway,
    RequestRefusedError,
    color_index,
)
from tests.conftest import get_json, login, open_dao


@pytest.fixture
def full_calls(gateway: MockGateway, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Chats the service asked Telegram about, in order; each answer comes from ``gateway.answers`` if set."""
    calls: list[int] = []
    answers: list[BaseException | ChannelFull] = []
    monkeypatch.setattr(gateway, "answers", answers, raising=False)

    async def get_full(channel_id: int) -> ChannelFull:
        calls.append(channel_id)
        answer = answers.pop(0) if answers else ChannelFull(about="About", members_count=10)

        if isinstance(answer, BaseException):
            raise answer

        return answer

    monkeypatch.setattr(gateway, "get_full", get_full)
    return calls


async def first_ids(client: httpx.AsyncClient, ctx: AppContext, n: int) -> list[int]:
    await login(client, ctx)
    return [item["id"] for item in (await get_json(client, "/api/channels"))["items"][:n]]


async def test_a_refusal_is_remembered_and_not_asked_again(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, full_calls: list[int]
) -> None:
    (cid,) = await first_ids(client, ctx, 1)
    gateway.answers.append(RequestRefusedError("CHANNEL_PRIVATE"))  # pyright: ignore[reportAttributeAccessIssue]

    first = await client.get(f"/api/channels/{cid}/full")
    second = await client.get(f"/api/channels/{cid}/full")

    # Not an error for the card: it is shown without extras and the UI stops asking
    assert first.status_code == second.status_code == 200
    assert (first.json()["full_loaded"], first.json()["full_error"]) == (True, "CHANNEL_PRIVATE")
    assert full_calls == [cid]


async def test_a_refusal_goes_stale_like_an_answer(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, full_calls: list[int]
) -> None:
    (cid,) = await first_ids(client, ctx, 1)
    gateway.answers.append(RequestRefusedError("CHANNEL_PRIVATE"))  # pyright: ignore[reportAttributeAccessIssue]
    await client.get(f"/api/channels/{cid}/full")
    ctx.settings.full_info_ttl_hours = 0

    r = await client.get(f"/api/channels/{cid}/full")

    assert full_calls == [cid, cid]
    assert (r.json()["about"], r.json()["full_error"]) == ("About", None)


async def test_a_dropped_connection_is_not_remembered(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, full_calls: list[int]
) -> None:
    (cid,) = await first_ids(client, ctx, 1)
    gateway.answers.append(GatewayError("No connection to Telegram"))  # pyright: ignore[reportAttributeAccessIssue]

    first = await client.get(f"/api/channels/{cid}/full")
    second = await client.get(f"/api/channels/{cid}/full")

    assert (first.status_code, second.status_code) == (502, 200)
    assert full_calls == [cid, cid]


async def test_a_flood_wait_holds_every_card(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, full_calls: list[int]
) -> None:
    first, second = await first_ids(client, ctx, 2)
    gateway.answers.append(FloodWaitError(120))  # pyright: ignore[reportAttributeAccessIssue]

    r1 = await client.get(f"/api/channels/{first}/full")
    r2 = await client.get(f"/api/channels/{second}/full")

    # The second card isn't sent to Telegram: it would get the same answer, and the wait would grow
    assert full_calls == [first]
    assert (r1.status_code, r1.json()["retry_after"]) == (429, 120)
    assert r2.status_code == 429
    assert 0 < r2.json()["retry_after"] <= 120


async def test_a_flood_wait_on_the_history_keeps_the_full_info(
    client: httpx.AsyncClient,
    ctx: AppContext,
    gateway: MockGateway,
    full_calls: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (cid,) = await first_ids(client, ctx, 1)

    async def flood(_: int, __: int) -> list[object]:
        raise FloodWaitError(60)

    monkeypatch.setattr(gateway, "recent_post_dates", flood)
    r = await client.get(f"/api/channels/{cid}/full")

    assert r.status_code == 200
    assert (r.json()["about"], r.json()["pulse"]) == ("About", None)
    # Without a pulse the row counts as not done: the next ask waits for the cooldown
    assert (await client.get(f"/api/channels/{cid}/full")).status_code == 429
    assert full_calls == [cid]

    async with open_dao(ctx) as dao:
        row = await dao.get_channel(ctx.auth.account_id, cid)

    assert row is not None
    assert row.about == "About"


async def test_a_flood_wait_on_pictures_holds_the_next_ones(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client, ctx)
    ids = [
        c["id"] for c in (await get_json(client, "/api/channels", params={"state": "all"}))["items"] if c["avatar_url"]
    ][:2]
    calls: list[int] = []

    async def flood(channel_id: int, *_: object) -> None:
        calls.append(channel_id)
        raise FloodWaitError(30)

    monkeypatch.setattr(gateway, "download_avatar", flood)

    statuses = [(await client.get(f"/api/channels/{cid}/avatar")).status_code for cid in ids]

    assert statuses == [429, 429]
    assert calls == ids[:1]


def test_a_card_opens_its_chat_in_telegram_at_the_last_post() -> None:
    assert telegram_url(-1001234567890, "rust_news", 512) == "tg://resolve?domain=rust_news&post=512"
    assert telegram_url(-1001234567890, "rust_news", None) == "tg://resolve?domain=rust_news"
    # A private one by its own id, without the -100 of the Bot API form
    assert telegram_url(-1001234567890, None, 7) == "tg://privatepost?channel=1234567890&post=7"


def test_a_chat_has_telegrams_colour() -> None:
    # Telegram Desktop: the channel's own id (no -100) modulo 7, unless its owner picked a colour
    assert color_index(-1001234567890, None) == 1234567890 % 7
    assert color_index(-1001234567890, 5) == 5
    assert color_index(-1001234567890, 13) == 6  # an extended palette falls back to a basic colour
