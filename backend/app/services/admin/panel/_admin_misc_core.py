"""Admin-panel service helpers for small panel utility blocks."""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session as AgentSession
from ....models import UsageEvent, User

_COST_PRECISION = Decimal("0.000001")


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _round_cost(value: Decimal) -> float:
    return float(value.quantize(_COST_PRECISION, rounding=ROUND_HALF_UP))


async def _load_usage_by_session(db: AsyncSession) -> list[tuple[str, dict[str, Any], str, str, int, int, Decimal]]:
    rows = (
        await db.execute(
            select(
                AgentSession.id,
                AgentSession.metadata_,
                User.id,
                User.username,
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost), 0),
            )
            .select_from(UsageEvent)
            .join(AgentSession, AgentSession.id == UsageEvent.session_id)
            .join(User, User.id == UsageEvent.user_id)
            # Group by the primary keys only: Postgres cannot GROUP BY the json
            # metadata_ column (no equality operator), and the other selected
            # columns are functionally dependent on these PKs.
            .group_by(AgentSession.id, User.id)
            .order_by(AgentSession.started_at.asc())
        )
    ).all()

    return [
        (
            str(session_id),
            dict(metadata or {}),
            str(user_id),
            str(username or ""),
            int(tokens_in or 0),
            int(tokens_out or 0),
            _to_decimal(cost),
        )
        for session_id, metadata, user_id, username, tokens_in, tokens_out, cost in rows
    ]


async def channel_stats(db: AsyncSession, *, channel_id: int) -> dict[str, Any]:
    session_count = 0
    message_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = Decimal("0")

    for _session_id, meta, _user_id, _username, tokens_in, tokens_out, cost in await _load_usage_by_session(db):
        if str(meta.get("channel_id") or "").strip() != str(channel_id):
            continue
        session_count += 1
        message_count += int(meta.get("message_count", 0))
        total_tokens_in += tokens_in
        total_tokens_out += tokens_out
        total_cost += cost

    return {
        "id": channel_id,
        "session_count": session_count,
        "message_count": message_count,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_cost": _round_cost(total_cost),
    }


def get_branding(*, load_branding_config_func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    return load_branding_config_func()


def update_branding(
    *,
    payload: dict[str, Any],
    save_branding_config_func: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    return save_branding_config_func(payload or {})


async def usage_stats(db: AsyncSession) -> dict[str, Any]:
    user_stats: dict[str, dict[str, Any]] = {}
    channel_stats_map: dict[str, dict[str, Any]] = {}
    total_cost = Decimal("0")
    total_tokens_in = 0
    total_tokens_out = 0
    total_sessions = 0

    for _session_id, meta, user_id, username, tokens_in, tokens_out, cost in await _load_usage_by_session(db):
        msg_count = int(meta.get("message_count") or 0)
        channel = str(meta.get("channel") or "").strip()

        total_sessions += 1
        total_cost += cost
        total_tokens_in += tokens_in
        total_tokens_out += tokens_out

        _add_user_usage(user_stats, user_id, username, tokens_in, tokens_out, cost, msg_count)
        _add_channel_usage(channel_stats_map, channel or "direct", cost, msg_count)

    return {
        "by_user": _ranked_by_cost(user_stats),
        "by_channel": _ranked_by_cost(channel_stats_map),
        "totals": {
            "total_cost": _round_cost(total_cost),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_sessions": total_sessions,
        },
    }


def _add_user_usage(
    user_stats: dict[str, dict[str, Any]],
    user_id: str,
    username: str,
    tokens_in: int,
    tokens_out: int,
    cost: Decimal,
    msg_count: int,
) -> None:
    if user_id not in user_stats:
        user_stats[user_id] = {
            "user_id": user_id,
            "username": username,
            "sessions": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost": Decimal("0"),
            "message_count": 0,
        }
    user_stats[user_id]["sessions"] += 1
    user_stats[user_id]["total_tokens_in"] += tokens_in
    user_stats[user_id]["total_tokens_out"] += tokens_out
    user_stats[user_id]["total_cost"] += cost
    user_stats[user_id]["message_count"] += msg_count


def _add_channel_usage(
    channel_stats_map: dict[str, dict[str, Any]], channel_key: str, cost: Decimal, msg_count: int
) -> None:
    if channel_key not in channel_stats_map:
        channel_stats_map[channel_key] = {
            "channel": channel_key,
            "sessions": 0,
            "message_count": 0,
            "total_cost": Decimal("0"),
        }
    channel_stats_map[channel_key]["sessions"] += 1
    channel_stats_map[channel_key]["message_count"] += msg_count
    channel_stats_map[channel_key]["total_cost"] += cost


def _ranked_by_cost(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    # Sorted on the exact Decimal totals; rounding happens only for the response.
    ranked = sorted(stats.values(), key=lambda item: item["total_cost"], reverse=True)
    for stat in ranked:
        stat["total_cost"] = _round_cost(stat["total_cost"])
    return ranked


__all__ = ["channel_stats", "get_branding", "update_branding", "usage_stats"]
