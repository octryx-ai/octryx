"""``handoff_now``: tell a session's launcher to hand its work over by itself."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence
from ...time_utils import utc_now
from .claim_values import iso

logger = logging.getLogger(__name__)

PROFILE_SEAT = "seat"
STATE_LIMIT_REACHED = "limit_reached"
NOT_NOW: dict[str, Any] = {}  # nothing is added to a hook answer below the trigger


async def _crossed(db: AsyncSession, presence: AgentPresence, trigger: float) -> bool:
    if presence.profile == PROFILE_SEAT:
        if presence.state == STATE_LIMIT_REACHED:
            return True
        return any(value is not None and value >= trigger for value in (presence.five_hour_pct, presence.seven_day_pct))
    from ..agent_gateway.daily_budget import check_daily_budget

    decision = await check_daily_budget(db, user_id=presence.user_id, workspace_id=presence.project_id)
    if decision.limit_usd is None or decision.limit_usd <= 0:
        return False
    return float(decision.spent_usd) >= float(decision.limit_usd) * trigger / 100


async def handoff_now(db: AsyncSession, *, session_key: str) -> dict[str, Any]:
    presence = (
        await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))
    ).scalar_one_or_none()
    if presence is None or presence.stopped_at is not None:
        return dict(NOT_NOW)
    from .auto_takeover import workspace_handoff_policy

    if presence.handoff_requested_at is not None:  # an admin's "Hand over now"
        return {"handoff_now": True, "handoff_crossing": f"requested-{iso(presence.handoff_requested_at)}"}
    policy = await workspace_handoff_policy(db, presence.project_id)
    if not await _crossed(db, presence, policy.auto_trigger_pct):
        if presence.handoff_crossing_at is not None:
            presence.handoff_crossing_at = None
            await db.flush()
        return dict(NOT_NOW)
    if presence.handoff_crossing_at is None:
        presence.handoff_crossing_at = utc_now()
        await db.flush()
    return {"handoff_now": True, "handoff_crossing": iso(presence.handoff_crossing_at),
            "handoff_trigger_pct": policy.auto_trigger_pct}


async def safe_handoff_now(db: AsyncSession, *, session_key: str) -> dict[str, Any]:
    try:
        async with db.begin_nested():
            return await handoff_now(db, session_key=session_key)
    except Exception:  # noqa: BLE001 - the handoff hint must never cost a tool call
        logger.warning("handoff_now evaluation failed for one session; the hook answer goes on", exc_info=True)
        return dict(NOT_NOW)


__all__ = ["handoff_now", "safe_handoff_now"]
