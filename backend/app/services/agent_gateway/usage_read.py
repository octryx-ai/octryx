"""What the launcher shows a user about their own usage.

``octryx-claude``'s status block reads, with the user's own gateway login:

- the **daily budget** of the Workspace (``daily_budget.check_daily_budget``: the user's gateway spend of the UTC
  day against the Workspace's ``session_budget.per_user_daily_usd``), with its explicit state;
- the user's **own seat allowance**: the latest 5h/7d utilization Anthropic reported on one of the user's seat
  sessions (``presence.record_allowance``). It is the user's own subscription, so any Workspace's presence row
  counts; only the numbers travel, never the Workspace or session of the row. The presence read model keeps other
  users' allowances for Workspace admins; this read never returns another user's row;
- the user's own **Codex seat allowance** (``codex_seat_allowance``): the same fields from ChatGPT's windows on one of
  the user's Codex seat sessions (``sessions.metadata.engine == codex``), kept apart from the Claude seat's.
"""

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
    """The newest allowance of the user's own seat sessions of ``engine`` (Claude Code: the Claude seat)."""
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
    """``{state, reason, workspace_id, limit_usd, spent_usd, resets_at, seat_allowance, codex_seat_allowance}``;
    amounts in USD."""
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
