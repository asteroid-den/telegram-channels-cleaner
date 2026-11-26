from __future__ import annotations

import httpx

from channels_cleaner.context import AppContext
from channels_cleaner.database import utc_now
from channels_cleaner.enums import ChatKind, Decision, DecisionStatus, RoleFilter
from channels_cleaner.services import SCOPE_VERSION, decisions
from tests.conftest import get_json, login, open_dao, wait_for


async def test_sort_dead_puts_never_posted_first(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels", params={"sort": "dead"}))["items"]
    dates = [item["last_post_at"] for item in items]
    nulls = [d for d in dates if d is None]
    assert dates[: len(nulls)] == nulls
    posted = [d for d in dates if d is not None]
    assert posted == sorted(posted)

    rev = await get_json(client, "/api/channels", params={"sort": "dead", "reverse": True})
    rev_dates = [item["last_post_at"] for item in rev["items"]]
    assert [d for d in rev_dates if d] == sorted(posted, reverse=True)
    assert rev_dates[len(posted) :] == nulls


async def test_sort_unread(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels", params={"sort": "unread"}))["items"]
    unread = [item["unread_count"] for item in items]
    assert unread == sorted(unread, reverse=True)


async def test_decide_undo_skip(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels"))["items"]
    a, b, c = items[0]["id"], items[1]["id"], items[2]["id"]

    r = await client.put(f"/api/decisions/{a}", json={"decision": "keep"})
    assert r.json()["counts"]["undecided"] == len(items) - 1
    await client.put(f"/api/decisions/{b}", json={"decision": "unsubscribe"})
    await client.put(f"/api/decisions/{c}", json={"decision": "skip"})

    deck = await get_json(client, "/api/channels")
    ids = [item["id"] for item in deck["items"]]
    assert a not in ids
    assert b not in ids
    assert ids[-1] == c  # skipped goes to the back
    assert deck["counts"]["pending"] == 1
    assert deck["counts"]["by_decision"] == {
        "keep": 1,
        "unsubscribe": 1,
        "mute": 0,
        "archive": 0,
        "transfer": 0,
        "delete": 0,
        "free_link": 0,
    }
    assert deck["counts"]["trail"] == "ku"  # in the order decided, skips left out

    undo = await client.delete(f"/api/decisions/{b}")
    assert undo.json()["ok"] is True
    assert (await get_json(client, "/api/channels"))["counts"]["pending"] == 0


async def test_full_info_is_lazy_and_cached(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    first = (await get_json(client, "/api/channels"))["items"][0]
    assert first["full_loaded"] is False
    full = await get_json(client, f"/api/channels/{first['id']}/full")
    assert full["full_loaded"] is True
    assert full["members_count"] is not None
    assert full["pulse"] is not None
    assert len(full["pulse"]["weeks"]) == 26


async def test_avatar_served(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels"))["items"]
    with_avatar = next(item for item in items if item["avatar_url"])
    response = await client.get(with_avatar["avatar_url"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg")


async def test_apply_review_stats_export(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels"))["items"]
    plan = {"unsubscribe": items[:6], "mute": items[6:8], "archive": items[8:9]}

    for decision, chosen in plan.items():
        for item in chosen:
            await client.put(f"/api/decisions/{item['id']}", json={"decision": decision})

    review = await get_json(client, "/api/decisions", params={"status": "pending"})
    assert len(review["items"]) == 9

    started = (await client.post("/api/apply")).json()
    assert started["status"] == "running"
    assert started["total"] == 9

    async def finished() -> bool:
        return bool((await get_json(client, "/api/apply/state"))["status"] == "finished")

    await wait_for(finished, timeout=60)
    final = await get_json(client, "/api/apply/state")
    assert final["done"] + final["failed"] == 9

    stats = await get_json(client, "/api/stats")
    unsubscribed = stats["decisions"]["unsubscribe"].get("applied", 0)
    assert stats["subscribed"] == len(items) - unsubscribed

    export = await client.get("/api/export", params={"format": "json"})
    assert len(export.json()) == unsubscribed
    csv = await client.get("/api/export", params={"format": "csv"})
    assert csv.text.startswith("channel_id,title")

    if final["failed"]:
        await client.post("/api/decisions/retry-failed")
        pending = await get_json(client, "/api/decisions", params={"status": "pending"})
        assert len(pending["items"]) == final["failed"]


async def test_changed_decision_keeps_its_place(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    items = (await get_json(client, "/api/channels"))["items"]
    a, b = items[0]["id"], items[1]["id"]
    await client.put(f"/api/decisions/{a}", json={"decision": "keep"})
    await client.put(f"/api/decisions/{b}", json={"decision": "unsubscribe"})
    r = await client.put(f"/api/decisions/{a}", json={"decision": "mute"})
    assert r.json()["counts"]["trail"] == "mu"  # changed in place, not moved to the end

    trail = (await get_json(client, "/api/decisions/trail"))["items"]
    assert [t["id"] for t in trail] == [a, b]
    assert [t["decision"] for t in trail] == ["mute", "unsubscribe"]


async def test_changing_an_applied_mute_queues_the_way_back(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    account = ctx.auth.account_id
    cid = (await get_json(client, "/api/channels"))["items"][0]["id"]

    async with open_dao(ctx) as dao:
        now = utc_now()
        await decisions.decide(dao, account, cid, Decision.MUTE, now)
        await dao.mark_decision(account, cid, DecisionStatus.APPLIED, expected=Decision.MUTE, now=now)

        await decisions.decide(dao, account, cid, Decision.KEEP, now)
        pending = await dao.list_decided(account, status=DecisionStatus.PENDING)
        assert [
            (c.channel_id, c.decision and c.decision.decision, c.decision and c.decision.reverts) for c in pending
        ] == [(cid, Decision.KEEP, Decision.MUTE)]

        # Changing it back to what Telegram already has needs no work at all
        await decisions.decide(dao, account, cid, Decision.MUTE, now)
        assert await dao.list_decided(account, status=DecisionStatus.PENDING) == []

        # Undo of a pending change restores the applied mute
        await decisions.decide(dao, account, cid, Decision.ARCHIVE, now)
        assert await decisions.undo(dao, account, cid)
        decision = await dao.get_decision(account, cid)
        assert decision is not None
        assert (decision.decision, decision.status, decision.reverts) == (Decision.MUTE, DecisionStatus.APPLIED, None)


async def test_channels_and_supergroups_are_separate_decks(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    channels = await get_json(client, "/api/channels")
    groups = await get_json(client, "/api/channels", params={"kind": "supergroup"})
    assert channels["counts"]["total"] == len(channels["items"])
    assert groups["counts"]["total"] == len(groups["items"])
    assert channels["counts"]["total"] + channels["counts"]["role_totals"]["managed"]["channel"] == 40
    assert groups["counts"]["total"] + groups["counts"]["role_totals"]["managed"]["supergroup"] == 25
    assert {item["kind"] for item in channels["items"]} == {"channel"}
    assert {item["kind"] for item in groups["items"]} == {"supergroup"}

    cid, gid = channels["items"][0]["id"], groups["items"][0]["id"]
    await client.put(f"/api/decisions/{cid}", json={"decision": "keep"})
    r = await client.put(f"/api/decisions/{gid}", json={"decision": "unsubscribe"})
    counts = r.json()["counts"]  # the kind comes from the channel itself
    assert counts["total"] == len(groups["items"])
    assert counts["trail"] == "u"
    assert counts["pending"] == 1
    assert counts["pending_other"] == 0

    channels = await get_json(client, "/api/channels")
    assert channels["counts"]["trail"] == "k"
    assert channels["counts"]["pending"] == 1  # review and apply cover both kinds
    assert channels["counts"]["pending_other"] == 1

    trail = await get_json(client, "/api/decisions/trail", params={"kind": "supergroup"})
    assert [t["id"] for t in trail["items"]] == [gid]
    assert (await get_json(client, "/api/stats", params={"kind": "supergroup"}))["subscribed"] == len(groups["items"])


async def test_sync_keeps_both_kinds_and_resyncs_old_lists(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    account = ctx.auth.account_id

    async with open_dao(ctx) as dao:
        assert await dao.count_channels(account) == 65
        assert await dao.get_setting(account, "synced_scope") == SCOPE_VERSION

    ctx.sync.start(account)
    await wait_for(lambda: apply_idle(ctx))

    async with open_dao(ctx) as dao:
        assert await dao.count_channels(account, ChatKind.SUPERGROUP) == 25
        assert await dao.count_channels(account, ChatKind.CHANNEL) == 40


async def apply_idle(ctx: AppContext) -> bool:
    return not ctx.sync.state.running


async def test_archive_filter_narrows_the_deck_and_its_counts(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    everything = await get_json(client, "/api/channels", params={"kind": "supergroup"})
    archived = await get_json(client, "/api/channels", params={"kind": "supergroup", "archive": "archived"})
    active = await get_json(client, "/api/channels", params={"kind": "supergroup", "archive": "active"})
    assert {i["is_archived"] for i in archived["items"]} == {True}
    assert {i["is_archived"] for i in active["items"]} == {False}
    assert len(archived["items"]) + len(active["items"]) == len(everything["items"])
    assert archived["counts"]["total"] == len(archived["items"])
    assert archived["counts"]["undecided"] == len(archived["items"])

    # a decision inside the filter only moves that filter's counters
    pick = archived["items"][0]["id"]
    await client.put(f"/api/decisions/{pick}", json={"decision": "keep"})
    after = await get_json(client, "/api/channels", params={"kind": "supergroup", "archive": "archived"})
    other = await get_json(client, "/api/channels", params={"kind": "supergroup", "archive": "active"})
    assert after["counts"]["trail"] == "k"
    assert other["counts"]["trail"] == ""
    trail = await get_json(client, "/api/decisions/trail", params={"kind": "supergroup", "archive": "archived"})
    assert [t["id"] for t in trail["items"]] == [pick]
    assert (await get_json(client, "/api/decisions/trail", params={"kind": "supergroup", "archive": "active"}))[
        "items"
    ] == []


async def test_archive_filter_saved_in_prefs_applies_to_answers(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    assert (
        await client.put("/api/prefs", json={"sort": "dead", "reverse": False, "archive": "archived"})
    ).status_code == 200
    items = (await get_json(client, "/api/channels", params={"archive": "archived"}))["items"]
    r = await client.put(f"/api/decisions/{items[0]['id']}", json={"decision": "unsubscribe"})
    counts = r.json()["counts"]  # no archive param: the saved filter decides
    assert counts["total"] == len(items)
    assert counts["trail"] == "u"


async def test_counts_tell_how_big_each_menu_choice_is(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    account = ctx.auth.account_id
    counts = (await get_json(client, "/api/channels", params={"kind": "supergroup"}))["counts"]

    async with open_dao(ctx) as dao:
        assert counts["kind_totals"] == {
            "channel": await dao.count_channels(account, ChatKind.CHANNEL, role=RoleFilter.MEMBER),
            "supergroup": await dao.count_channels(account, ChatKind.SUPERGROUP, role=RoleFilter.MEMBER),
        }

    totals = counts["archive_totals"]
    assert totals["all"] == counts["total"]
    assert totals["active"] + totals["archived"] == totals["all"]

    archived = (await get_json(client, "/api/channels", params={"kind": "supergroup", "archive": "archived"}))["counts"]
    assert archived["total"] == totals["archived"]
    assert archived["archive_totals"] == totals  # the menu keeps showing all choices
    assert archived["kind_totals"]["supergroup"] == totals["archived"]


async def test_chats_the_user_runs_have_their_own_deck(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    mine = await get_json(client, "/api/channels", params={"role": "managed"})
    others = await get_json(client, "/api/channels")
    assert mine["items"], "the mock has some chats the user runs"
    assert {i["role"] for i in mine["items"]} <= {"admin", "owner"}
    assert {i["role"] for i in others["items"]} == {"member"}
    assert mine["counts"]["role_totals"] == others["counts"]["role_totals"]
    assert mine["counts"]["role_totals"]["managed"]["channel"] == len(mine["items"])
    assert mine["counts"]["role_totals"]["member"]["supergroup"] > 0  # both kinds, whichever deck is open

    # a decision lands in the deck of the chat's own role
    pick = mine["items"][0]["id"]
    r = await client.put(
        f"/api/decisions/{pick}", json={"decision": "keep" if mine["items"][0]["role"] == "owner" else "mute"}
    )
    assert r.json()["counts"]["total"] == len(mine["items"])
    assert (await get_json(client, "/api/channels"))["counts"]["trail"] == ""
    assert (await get_json(client, "/api/channels", params={"role": "managed"}))["counts"]["trail"] != ""
    assert (await get_json(client, "/api/stats", params={"role": "managed"}))["subscribed"] == len(mine["items"])


async def owned_chat_id(client: httpx.AsyncClient) -> int:
    items = (await get_json(client, "/api/channels", params={"role": "managed"}))["items"]
    return next(i["id"] for i in items if i["role"] == "owner")


async def test_leaving_an_owned_chat_is_off_by_default(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    owned = await owned_chat_id(client)
    refused = await client.put(f"/api/decisions/{owned}", json={"decision": "unsubscribe"})
    assert refused.status_code == 409
    assert (await client.put(f"/api/decisions/{owned}", json={"decision": "mute"})).status_code == 200

    # an admin may leave: only the creator is protected
    items = (await get_json(client, "/api/channels", params={"role": "managed"}))["items"]
    admin = next(i["id"] for i in items if i["role"] == "admin")
    assert (await client.put(f"/api/decisions/{admin}", json={"decision": "unsubscribe"})).status_code == 200
    assert (await get_json(client, "/api/health"))["allow_owner_leave"] is False


async def test_owner_leave_flag_allows_it(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    ctx.settings.allow_owner_leave = True
    owned = await owned_chat_id(client)
    assert (await client.put(f"/api/decisions/{owned}", json={"decision": "unsubscribe"})).status_code == 200

    async def finished() -> bool:
        return bool((await get_json(client, "/api/apply/state"))["status"] == "finished")

    await client.post("/api/apply")
    await wait_for(finished, timeout=30)
    state = await get_json(client, "/api/apply/state")
    assert state["done"] + state["failed"] == 1
    assert (
        state["failed"] == 0
        or state["items"][0]["error"] != "Leaving a chat you own is off (start with --allow-owner-leave)"
    )


async def test_queued_owner_leave_fails_when_the_flag_is_off(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    ctx.settings.allow_owner_leave = True
    owned = await owned_chat_id(client)
    await client.put(f"/api/decisions/{owned}", json={"decision": "unsubscribe"})
    ctx.settings.allow_owner_leave = False  # e.g. the app was restarted without the flag

    await client.post("/api/apply")

    async def finished() -> bool:
        return bool((await get_json(client, "/api/apply/state"))["status"] == "finished")

    await wait_for(finished, timeout=30)
    state = await get_json(client, "/api/apply/state")
    assert state["failed"] == 1
    assert "off" in state["items"][0]["error"]


async def test_reset_and_undo_tell_what_they_removed(client: httpx.AsyncClient, ctx: AppContext) -> None:
    await login(client, ctx)
    first, second = [item["id"] for item in (await get_json(client, "/api/channels"))["items"][:2]]
    await client.put(f"/api/decisions/{first}", json={"decision": "keep"})
    await client.put(f"/api/decisions/{second}", json={"decision": "unsubscribe"})

    assert (await client.delete(f"/api/decisions/{second}")).json()["removed"] is True
    assert (await client.delete(f"/api/decisions/{second}")).json()["removed"] is False
    assert (await client.post("/api/decisions/reset", json={})).json()["removed"] == 1
