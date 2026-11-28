"""Budget and seat-allowance warnings: governed daily budget at 80 %, seat 5h/7d allowance at 95 %."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun

BUDGET_WARN_RATIO = 0.8
ALLOWANCE_WARN_PCT = 95.0
# Operations › Usage & costs.
USAGE_HREF = "/chat?area=operations&tab=usage"


async def _workspaces(db: AsyncSession, user: User) -> list[str]:
    rows = (await db.execute(select(WorkflowRun.project_id).where(
        WorkflowRun.requested_by == user.id, WorkflowRun.project_id.is_not(None),
    ).order_by(WorkflowRun.updated_at.desc()).limit(20))).scalars().all()
    return list(dict.fromkeys(rows))[:5]


async def threshold_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from ..agent_gateway.usage_read import own_gateway_usage, own_seat_allowance

    entries: list[dict[str, Any]] = []
    for workspace_id in await _workspaces(db, user):
        usage = await own_gateway_usage(db, user_id=user.id, workspace_id=workspace_id)
        limit, spent = usage.get("limit_usd"), usage.get("spent_usd")
        if limit and spent is not None and spent / limit >= BUDGET_WARN_RATIO:
            entries.append({
                "key": f"budget:{workspace_id}:{usage.get('resets_at')}", "kind": "budget", "id": workspace_id,
                "title": f"Daily budget {spent:.2f} / {limit:.2f} USD", "subtitle": "governed model use today",
                "text": f"{spent / limit:.0%} of your daily budget is used; it resets at {usage.get('resets_at')}.",
                "created_at": None, "severity": "warning", "workspace": {"id": workspace_id, "name": ""},
                "run": None, "work_item": None, "session_id": None,
                "link": {"href": USAGE_HREF, "label": "Open usage"}, "actions": [],
            })
            break  # one budget warning: the spend is per person across Workspaces
    seat = await own_seat_allowance(db, user_id=user.id)
    for window, pct_key, reset_key in (("5h", "five_hour_pct", "five_hour_resets_at"),
                                       ("7d", "seven_day_pct", "seven_day_resets_at")):
        pct = (seat or {}).get(pct_key)
        if pct is not None and pct >= ALLOWANCE_WARN_PCT:
            entries.append({
                "key": f"allowance:{window}:{(seat or {}).get(reset_key)}", "kind": "allowance", "id": window,
                "title": f"Seat allowance {window} at {pct:.0f} %", "subtitle": "your Claude seat",
                "text": (f"The {window} window of your seat is at {pct:.0f} %; at 99 % running work is handed over. "
                         f"It resets at {(seat or {}).get(reset_key)}."),
                "created_at": (seat or {}).get("updated_at"), "severity": "warning", "workspace": None, "run": None,
                "work_item": None, "session_id": None, "link": {"href": USAGE_HREF, "label": "Open usage"},
                "actions": [],
            })
    return entries


__all__ = ["threshold_entries"]
