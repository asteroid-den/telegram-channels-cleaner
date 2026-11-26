from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from channels_cleaner.database import DAO
from channels_cleaner.enums import LEAVING_ACTIONS, ChatKind, DecisionStatus, RoleFilter

AGE_BUCKETS: list[tuple[str, float]] = [
    ("week", 7),
    ("month", 30),
    ("quarter", 90),
    ("half_year", 182),
    ("year", 365),
    ("older", float("inf")),
]


async def collect(
    dao: DAO, account_id: int, kind: ChatKind = ChatKind.CHANNEL, role: RoleFilter = RoleFilter.MEMBER
) -> dict[str, Any]:
    by_decision: dict[str, dict[str, int]] = {}

    for decision, status, count in await dao.decision_status_counts(account_id, kind, role):
        by_decision.setdefault(decision, {})[status] = count

    rows = await dao.list_subscribed(account_id, kind, role)
    now = datetime.now(UTC)
    age = {name: 0 for name, _ in AGE_BUCKETS} | {"never": 0}
    unread_total = 0

    for last_post_at, unread in rows:
        unread_total += unread

        if last_post_at is None:
            age["never"] += 1
            continue

        days = (now - last_post_at).total_seconds() / 86400

        for name, limit in AGE_BUCKETS:
            if days <= limit:
                age[name] += 1
                break

    return {
        "subscribed": len(rows),
        "unread_total": unread_total,
        "unread_cleared": await dao.unread_cleared(account_id, kind, role),
        "decisions": by_decision,
        "last_post_age": age,
    }


async def export_rows(
    dao: DAO, account_id: int, kind: ChatKind = ChatKind.CHANNEL, role: RoleFilter = RoleFilter.MEMBER
) -> list[dict[str, Any]]:
    channels = await dao.list_decided(
        account_id, status=DecisionStatus.APPLIED, decisions=LEAVING_ACTIONS, kind=kind, role=role
    )
    return [
        {
            "channel_id": channel.channel_id,
            "title": channel.title,
            "username": channel.username,
            "link": f"https://t.me/{channel.username}" if channel.username else None,
            "members_count": channel.members_count,
            "last_post_at": iso(channel.last_post_at),
            "unsubscribed_at": iso(channel.decision.applied_at if channel.decision else None),
        }
        for channel in channels
    ]


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    fields = [
        "channel_id",
        "title",
        "username",
        "link",
        "members_count",
        "last_post_at",
        "unsubscribed_at",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
