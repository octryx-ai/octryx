"""Explicit work-item redeclaration after a rejected delivery.

When a delivered PR is declined, the work item must be plannable again
without losing the audit trail: every open or approved plan is superseded
(with a decision record), every active change unit is superseded, and the
redeclaration itself is audited with the operator's reason. Re-planning then
uses the normal plan/unit endpoints and the acceptance-coverage gate.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkChangePlan,
    WorkChangePlanDecision,
    WorkItem,
    WorkItemChangeUnit,
)
from ....time_utils import utc_now
from ..jira_values import blank_to_none, object_value
from .plan_write_lock import lock_work_item_for_plan_write

SUPERSEDED_UNIT_STATUS = "superseded"
REDECLARABLE_PLAN_STATUSES = {"draft", "needs_clarification", "ready_for_review", "approved"}


async def redeclare_work_item(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    reason = blank_to_none(payload.get("reason"))
    if not reason:
        raise HTTPException(status_code=422, detail="Redeclaration requires a reason (e.g. the declined PR)")
    # Same per-Work-Item plan write lock as generation, answers and decisions; the plans
    # below are read fresh, not from copies loaded before the lock.
    item = await lock_work_item_for_plan_write(db, item.id)

    now = utc_now()
    plans = (
        await db.execute(
            select(WorkChangePlan)
            .where(
                WorkChangePlan.work_item_id == item.id,
                WorkChangePlan.status.in_(REDECLARABLE_PLAN_STATUSES),
            )
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    for plan in plans:
        db.add(
            WorkChangePlanDecision(
                change_plan_id=plan.id,
                work_item_id=item.id,
                actor_id=current_user.id,
                action="redeclare",
                from_status=plan.status,
                to_status="superseded",
                reason=reason,
                required_changes_json=[],
                jira_sync_preview_json={},
                evidence_json=object_value(payload.get("evidence")),
            )
        )
        plan.status = "superseded"
        plan.updated_by = current_user.id
        plan.decided_by = current_user.id
        plan.decided_at = now

    units = (
        await db.execute(
            select(WorkItemChangeUnit).where(
                WorkItemChangeUnit.work_item_id == item.id,
                WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
            )
        )
    ).scalars().all()
    for unit in units:
        unit.status = SUPERSEDED_UNIT_STATUS
        unit.updated_by = current_user.id

    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.work_item_redeclared",
            resource_type="work_item",
            resource_id=item.id,
            details={
                "source_key": item.source_key,
                "reason": reason,
                "superseded_plan_ids": [plan.id for plan in plans],
                "superseded_unit_ids": [unit.id for unit in units],
            },
        )
    )
    await db.flush()
    return {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "reason": reason,
        "superseded_plans": len(plans),
        "superseded_units": len(units),
    }


__all__ = ["SUPERSEDED_UNIT_STATUS", "redeclare_work_item"]
