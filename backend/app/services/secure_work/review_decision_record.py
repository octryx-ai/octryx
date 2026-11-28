"""Explicit Coding review decisions: validation and the server-owned decision record."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkChangePlan, WorkItem, WorkItemChangeUnit
from ...time_utils import utc_now
from .jira_values import iso
from .plans.redeclare import SUPERSEDED_UNIT_STATUS

DECISION_RECORD_KEY = "review_decision_record"
DECISION_RECORD_SCHEMA = "coding_review_decision.v1"
REVIEW_DECISIONS = ("approved", "changes_requested", "rejected")
DECISION_EVENT_TYPE = "review_decision"
SCOPE_CHANGE_UNIT = "change_unit"
SCOPE_WORK_ITEM = "work_item"
ACTOR_LABEL_LIMIT = 120
MARKER_LIMIT = 64


def without_reserved_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    # The decision record is server-owned: a caller can never store a forged one
    return {key: value for key, value in metadata.items() if key != DECISION_RECORD_KEY}


def unit_update_marker(unit: WorkItemChangeUnit) -> str:
    # Exactly as the API serializes it: the UI sends it back, so an older reviewed state goes stale.
    return iso(unit.updated_at) or ""


def actor_label(user: User) -> str:
    # Never the raw id.
    label = (user.display_name or user.username or user.email or "Reviewer").strip() or "Reviewer"
    return label[:ACTOR_LABEL_LIMIT]


async def latest_plan(db: AsyncSession, work_item_id: str) -> WorkChangePlan | None:
    return (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == work_item_id)
            .order_by(WorkChangePlan.version.desc())
            .limit(1)
        )
    ).scalars().first()


async def validated_decision_record(
    db: AsyncSession,
    *,
    item: WorkItem,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if "decision" not in payload:
        return None
    decision = payload.get("decision")
    if not isinstance(decision, str) or decision not in REVIEW_DECISIONS:
        raise HTTPException(status_code=422, detail=f"decision must be one of: {', '.join(REVIEW_DECISIONS)}")
    if payload.get("event_type") != DECISION_EVENT_TYPE:
        raise HTTPException(status_code=422, detail="A decision can only be recorded on a review_decision event")
    plan_id = payload.get("change_plan_id")
    expected_version = payload.get("expected_plan_version")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise HTTPException(status_code=422, detail="change_plan_id is required for a review decision")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise HTTPException(status_code=422, detail="expected_plan_version must be an integer")

    plan = await db.get(WorkChangePlan, plan_id.strip())
    if plan is None or plan.work_item_id != item.id:
        raise HTTPException(status_code=404, detail="Change Plan not found for this Work Item")
    newest = await latest_plan(db, item.id)
    if newest is None or newest.id != plan.id or newest.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail="The plan changed since it was displayed; reload and review the latest plan version",
        )

    unit_id = payload.get("change_unit_id")
    marker = payload.get("expected_change_unit_marker")
    record: dict[str, Any] = {
        "schema": DECISION_RECORD_SCHEMA,
        "decision": decision,
        "actor_id": current_user.id,
        "actor_label": actor_label(current_user),
        "change_plan_id": plan.id,
        "plan_version": plan.version,
        "recorded_at": utc_now().isoformat(),
    }
    if unit_id is None or unit_id == "":
        has_active_units = (
            await db.execute(
                select(WorkItemChangeUnit.id)
                .where(
                    WorkItemChangeUnit.work_item_id == item.id,
                    WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
                )
                .limit(1)
            )
        ).first() is not None
        if has_active_units:
            raise HTTPException(
                status_code=422,
                detail="This Work Item has active Change Units; choose the Change Unit this decision covers",
            )
        if marker not in (None, ""):
            raise HTTPException(status_code=422, detail="A whole Work Item decision takes no Change Unit marker")
        return {**record, "scope": SCOPE_WORK_ITEM, "change_unit_id": None, "change_unit_marker": None}
    if not isinstance(unit_id, str):
        raise HTTPException(status_code=422, detail="change_unit_id must be a string")
    # The first read of the reviewed unit in this request takes a row lock (PostgreSQL; a no-op on
    # SQLite) held until the decision is committed, so the state checked here is the state the
    # decision is recorded against; a later unit write changes the marker and the decision goes stale.
    unit = (
        await db.execute(select(WorkItemChangeUnit).where(WorkItemChangeUnit.id == unit_id).with_for_update())
    ).scalars().first()
    if unit is None or unit.work_item_id != item.id:
        raise HTTPException(status_code=404, detail="Change Unit not found for this Work Item")
    if unit.status == SUPERSEDED_UNIT_STATUS:
        raise HTTPException(status_code=409, detail="The Change Unit is superseded; review an active Change Unit")
    if not isinstance(marker, str) or not marker.strip() or len(marker) > MARKER_LIMIT:
        raise HTTPException(
            status_code=422,
            detail="expected_change_unit_marker must be the displayed Change Unit state (its updated_at)",
        )
    if marker != unit_update_marker(unit):
        raise HTTPException(
            status_code=409,
            detail="The Change Unit changed since it was displayed; reload and review its current state",
        )
    return {
        **record,
        "scope": SCOPE_CHANGE_UNIT,
        "change_unit_id": unit.id,
        "change_unit_marker": unit_update_marker(unit),
    }
