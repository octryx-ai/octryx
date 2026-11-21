"""How often each agent ran in the last 30 days: chat sessions bound to it (Agents list "Used (30 d)")."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session
from ..time_utils import utc_now

USAGE_WINDOW_DAYS = 30


async def agent_usage_counts(db: AsyncSession, *, days: int = USAGE_WINDOW_DAYS) -> dict[str, int]:
    agent_id = Session.metadata_["agent_definition_id"].as_string()
    rows = await db.execute(
        select(agent_id, func.count())
        .where(Session.started_at >= utc_now() - timedelta(days=days), agent_id.is_not(None))
        .group_by(agent_id)
    )
    return {str(key): int(count) for key, count in rows.all() if key}


__all__ = ["USAGE_WINDOW_DAYS", "agent_usage_counts"]
