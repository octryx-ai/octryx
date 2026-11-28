"""What the launcher shows a user about their own usage: the daily budget and their own seat allowances."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Session
from .daily_budget import check_daily_budget
from .engine_keys import ENGINE_CLAUDE_CODE, ENGINE_CODEX, SESSION_ENGINE_KEY
from .seat_credential import PROFILE_SEAT


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value is not None else None


_SCAN = 50  # the user's newest seat rows with an allowance, read to find the newest of one engine


def _engine(metadata: object) -> str:
    engine = metadata.get(SESSION_ENGINE_KEY) if isinstance(metadata, dict) else None
    return ENGINE_CODEX if engine == ENGINE_CODEX else ENGINE_CLAUDE_CODE


async def own_seat_allowance(db: AsyncSession, *, user_id: str, engine: str = ENGINE_CLAUDE_CODE
                             ) -> dict[str, Any] | None:
    rows = (
        await db.execute(
            select(AgentPresence, Session.metadata_)
            .outerjoin(Session, Session.id == AgentPresence.session_id)
            .where(
                AgentPresence.user_id == user_id,
                AgentPresence.profile == PROFILE_SEAT,
                AgentPresence.allowance_updated_at.is_not(None),
            )
            .order_by(AgentPresence.allowance_updated_at.desc())
            .limit(_SCAN)
        )
    ).all()
    row = next((presence for presence, metadata in rows if _engine(metadata) == engine), None)
    if row is None:
        return None
    return {
        "five_hour_pct": row.five_hour_pct,
        "five_hour_resets_at": _iso(row.five_hour_resets_at),
        "seven_day_pct": row.seven_day_pct,
        "seven_day_resets_at": _iso(row.seven_day_resets_at),
        "status": row.allowance_status,
        "updated_at": _iso(row.allowance_updated_at),
    }


async def own_gateway_usage(db: AsyncSession, *, user_id: str, workspace_id: str) -> dict[str, Any]:
    budget = await check_daily_budget(db, user_id=user_id, workspace_id=workspace_id)
    configured = budget.limit_usd is not None
    return {
        "state": budget.state,
        "reason": budget.reason or None,
        "workspace_id": workspace_id,
        "limit_usd": float(budget.limit_usd) if configured else None,
        "spent_usd": float(budget.spent_usd) if configured else None,
        "resets_at": _iso(budget.resets_at),
        "seat_allowance": await own_seat_allowance(db, user_id=user_id),
        "codex_seat_allowance": await own_seat_allowance(db, user_id=user_id, engine=ENGINE_CODEX),
    }


__all__ = ["own_gateway_usage", "own_seat_allowance"]
