from __future__ import annotations

import httpx
import pytest

from channels_cleaner.app import create_app
from channels_cleaner.context import AppContext
from channels_cleaner.telegram import MockGateway
from channels_cleaner.telegram.mock_gateway import MOCK_USER, MOCK_USERS
from tests.conftest import get_json, login, wait_for

WORK = MOCK_USERS[1]


async def add_second(client: httpx.AsyncClient, ctx: AppContext) -> None:
    assert (await client.post("/api/accounts/add")).json()["status"] == "unauthorized"
    await login(client, ctx)


async def two_accounts(client: httpx.AsyncClient, ctx: AppContext) -> None:
    """The first mock user, then a second one added: the second is active."""
    await login(client, ctx)
    await add_second(client, ctx)


async def accounts(client: httpx.AsyncClient) -> list[tuple[int, bool]]:
    return [(item["id"], item["active"]) for item in (await get_json(client, "/api/accounts"))["items"]]


async def titles(client: httpx.AsyncClient) -> list[str]:
    return [item["title"] for item in (await get_json(client, "/api/channels", params={"state": "all"}))["items"]]


async def test_a_second_account_logs_in_next_to_the_first(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    first_titles = await titles(client)

    await add_second(client, ctx)

    assert (await get_json(client, "/api/auth/state"))["user"]["id"] == WORK.id
    assert await accounts(client) == [(MOCK_USER.id, False), (WORK.id, True)]
    # Each account has its own chats
    assert await titles(client) != first_titles


async def test_switching_brings_back_the_other_accounts_decisions(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    cid = (await get_json(client, "/api/channels"))["items"][0]["id"]
    assert (await client.put(f"/api/decisions/{cid}", json={"decision": "unsubscribe"})).status_code == 200
    await add_second(client, ctx)
    assert (await get_json(client, "/api/channels"))["counts"]["pending"] == 0

    r = await client.post(f"/api/accounts/{MOCK_USER.id}/activate")

    assert r.json()["user"]["id"] == MOCK_USER.id
    assert (await get_json(client, "/api/channels"))["counts"]["pending"] == 1
    listed = (await get_json(client, "/api/accounts"))["items"]
    assert [(item["id"], item["pending"]) for item in listed] == [(MOCK_USER.id, 1), (WORK.id, 0)]


async def test_no_switching_while_the_job_runs(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway
) -> None:
    await two_accounts(client, ctx)
    cid = (await get_json(client, "/api/channels"))["items"][0]["id"]
    await client.put(f"/api/decisions/{cid}", json={"decision": "mute"})
    gateway.action_delay = 0.3
    assert (await client.post("/api/apply")).status_code == 200

    r = await client.post(f"/api/accounts/{MOCK_USER.id}/activate")

    assert (r.status_code, r.json()["type"]) == (409, "apply_job_running")
    assert (await get_json(client, "/api/auth/state"))["user"]["id"] == WORK.id


async def test_an_unknown_account_is_refused(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)

    r = await client.post("/api/accounts/42/activate")

    assert (r.status_code, r.json()["type"]) == (404, "account_not_found")


async def test_giving_up_an_added_login_leaves_no_session(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    await client.post("/api/accounts/add")

    r = await client.post(f"/api/accounts/{MOCK_USER.id}/activate")

    assert r.json()["status"] == "authorized"
    assert sorted(path.name for path in ctx.settings.data_dir.glob("mock_*.json")) == ["mock_session.json"]


async def test_logging_out_hands_over_to_another_account(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await two_accounts(client, ctx)

    r = await client.post("/api/auth/logout", json={"wipe_data": False})

    assert (r.json()["status"], r.json()["user"]["id"]) == ("authorized", MOCK_USER.id)
    assert await accounts(client) == [(MOCK_USER.id, True)]


async def test_logging_out_of_the_last_one_asks_for_a_login(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)

    r = await client.post("/api/auth/logout", json={"wipe_data": False})

    assert r.json()["status"] == "unauthorized"
    assert await accounts(client) == []


async def test_the_last_active_account_comes_back_on_start(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await two_accounts(client, ctx)
    await ctx.shutdown()

    restarted = AppContext.create(ctx.settings, MockGateway(ctx.settings))
    app = create_app(ctx.settings, restarted)

    async with app.router.lifespan_context(app):
        await restarted.wait_ready()

        async def connected() -> bool:
            return restarted.auth.state.status == "authorized"

        await wait_for(connected)
        assert restarted.auth.state.user is not None
        assert restarted.auth.state.user.id == WORK.id


async def test_an_accounts_photo_is_served_and_listed(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)

    # Fetched after the login, next to the sync
    await wait_for(lambda: has_photo(ctx, MOCK_USER.id))
    url = (await get_json(client, "/api/accounts"))["items"][0]["avatar_url"]
    r = await client.get(url)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


async def test_an_account_without_a_photo_gets_none(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    await add_second(client, ctx)
    await client.post("/api/accounts/add")
    await login(client, ctx)  # the third mock user has no photo

    third = (await get_json(client, "/api/accounts"))["items"][-1]
    r = await client.get(f"/api/accounts/{third['id']}/avatar")

    assert third["avatar_url"] is None
    assert (r.status_code, r.json()["type"]) == (404, "avatar_not_found")


async def test_a_photo_removed_in_telegram_goes_here_too(
    client: httpx.AsyncClient, ctx: AppContext, gateway: MockGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(client, ctx)
    await wait_for(lambda: has_photo(ctx, MOCK_USER.id))

    async def none(_: object) -> None:
        return None

    monkeypatch.setattr(gateway, "download_own_photo", none)
    await ctx.channels.refresh_own_photo(MOCK_USER.id)

    assert ctx.channels.own_photo(MOCK_USER.id) is None


async def has_photo(ctx: AppContext, account_id: int) -> bool:
    return ctx.channels.own_photo(account_id) is not None
