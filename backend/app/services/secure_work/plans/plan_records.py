"""Shared Change Plan records: versions, superseding, Jira sync previews and audit rows (a plan's workflow is
loaded through ``related_rows.load_related``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkChangePlan,
    WorkItem,
    WorkItemWorkflowDefinition,
)
from ....time_utils import utc_now
from ..sync_policy import mapped_status, mapped_transition

OPEN_PLAN_STATUSES = {"draft", "needs_clarification", "ready_for_review"}


async def _next_version(db: AsyncSession, work_item_id: str) -> int:
    max_version = (
        await db.execute(select(func.max(WorkChangePlan.version)).where(WorkChangePlan.work_item_id == work_item_id))
    ).scalar_one_or_none()
    return int(max_version or 0) + 1


async def _supersede_open_plans(
    db: AsyncSession,
    work_item_id: str,
    actor_id: str,
    supersede_existing: bool,
) -> str | None:
    if not supersede_existing:
        return None
    rows = (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == work_item_id, WorkChangePlan.status.in_(OPEN_PLAN_STATUSES))
            .order_by(WorkChangePlan.version.desc())
        )
    ).scalars().all()
    superseded_plan_id = rows[0].id if rows else None
    now = utc_now()
    for row in rows:
        row.status = "superseded"
        row.updated_by = actor_id
        row.decided_by = actor_id
        row.decided_at = now
    return superseded_plan_id


def _jira_sync_preview(
    *,
    workflow: WorkItemWorkflowDefinition | None,
    target_state: str,
    source: str,
) -> dict[str, Any]:
    mapping = dict((workflow.mappings_json or {}).get(target_state) or {}) if workflow else {}
    return {
        "mode": "preview",
        "source": source,
        "workflow_id": workflow.id if workflow else None,
        "target_state": target_state,
        "will_mutate_jira": False,
        "sync_back": bool(mapping.get("sync_back")),
        "target_status": mapped_status(mapping),
        "transition": mapped_transition(mapping),
        "comment_template": mapping.get("comment_template"),
        "labels": list(mapping.get("labels") or []),
        "custom_fields": dict(mapping.get("custom_fields") or {}),
    }


def _audit_log(current_user: User, item: WorkItem, action: str, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type="work_item",
        resource_id=item.id,
        project_id=item.project_id,
        details={"source_key": item.source_key, **details},
    )
