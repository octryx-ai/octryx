"""What a coding agent execution start records and returns: session metadata, audit entries, the result views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, Session, User, WorkChangePlan, WorkCodingAuditEvent, WorkItem, WorkItemChangeUnit
from ....time_utils import utc_now
from .coding_workspaces import workspace_metadata_patch
from .execution_scope import _delivery_context


@dataclass(frozen=True)
class ExecutionStart:
    """One started coding agent execution, as the start records need it."""

    item: WorkItem
    plan: WorkChangePlan
    units: list[WorkItemChangeUnit]
    pipeline_run: dict[str, Any]
    session: Session
    workspaces: list[dict[str, Any]]
    prompt: str
    current_user: User
    restart_from_scratch: bool
    restart_reason: str


async def _record_execution_start(db: AsyncSession, started: ExecutionStart) -> None:
    from .verification_contract import resolve_verification_contract

    item, plan, units, session = started.item, started.plan, started.units, started.session
    metadata = dict(session.metadata_ or {})
    metadata["secure_work_execution"] = {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_plan_id": plan.id,
        "change_unit_ids": [unit.id for unit in units],
        "pipeline_run_id": started.pipeline_run.get("id"),
        "started_by": started.current_user.id,
        "started_at": utc_now().isoformat(),
        "restart_from_scratch": started.restart_from_scratch,
        "restart_reason": started.restart_reason or None,
        "workspaces": started.workspaces,
        # Approved verification contract: the step machine builds its success
        # criterion from it and run_validation_commands executes exactly it.
        "verification_contract": resolve_verification_contract(plan=plan, units=units),
        # Provider context for the delivery hand-off step. Unknown or mixed
        # providers resolve to no delivery step, never to a guessed one.
        "delivery": await _delivery_context(db, item=item, units=units),
    }
    metadata.update(workspace_metadata_patch(started.workspaces))
    session.metadata_ = metadata
    db.add(_execution_audit_event(started))
    db.add(
        _audit_log(
            started.current_user,
            item,
            "secure_work.coding_agent_execution_started",
            {
                "session_id": session.id,
                "change_plan_id": plan.id,
                "pipeline_run_id": started.pipeline_run.get("id"),
                "change_unit_ids": [unit.id for unit in units],
                "workspace_ids": [
                    str(workspace.get("id") or "") for workspace in started.workspaces if workspace.get("id")
                ],
                "restart_from_scratch": started.restart_from_scratch,
                "restart_reason": started.restart_reason or None,
            },
        )
    )


def _execution_audit_event(started: ExecutionStart) -> WorkCodingAuditEvent:
    restart_from_scratch = started.restart_from_scratch
    return WorkCodingAuditEvent(
        work_item_id=started.item.id,
        pipeline_run_id=started.pipeline_run.get("id"),
        event_type="agent_execution_restarted" if restart_from_scratch else "agent_execution_started",
        title="Coding agent execution restarted" if restart_from_scratch else "Coding agent execution started",
        summary=(
            "Octryx started a fresh governed coding agent session after operator restart."
            if restart_from_scratch
            else "Octryx started a governed coding agent session from an approved Work Plan."
        ),
        actor_kind="platform",
        actor_id=started.current_user.id,
        evidence_json={
            "session_id": started.session.id,
            "change_plan_id": started.plan.id,
            "change_unit_ids": [unit.id for unit in started.units],
            "pipeline_run_id": started.pipeline_run.get("id"),
            "workspaces": started.workspaces,
            "prompt_preview": started.prompt[:4000],
            "restart_from_scratch": restart_from_scratch,
            "restart_reason": started.restart_reason or None,
        },
        metadata_json={"source": "secure_work_coding_execution"},
        created_at=utc_now(),
    )


def _audit_log(current_user: User, item: WorkItem, action: str, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type="secure_work_coding_execution",
        resource_id=item.id,
        details={"work_item_id": item.id, "source_key": item.source_key, **details},
    )


def _blocked_execution(
    db: AsyncSession,
    item: WorkItem,
    plan: WorkChangePlan,
    pipeline_run: dict[str, Any],
    blockers: list[Any],
    current_user: User,
) -> dict[str, Any]:
    db.add(
        _audit_log(
            current_user,
            item,
            "secure_work.coding_agent_execution_blocked",
            {
                "change_plan_id": plan.id,
                "pipeline_run_id": pipeline_run.get("id"),
                "blockers": blockers,
            },
        )
    )
    return {
        "status": "blocked",
        "reason": "coding_pipeline_policy_blocked",
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_plan_id": plan.id,
        "work_url": _work_item_url(item),
        "coding_url": _coding_work_item_url(item),
        "next_actions": _blocked_next_actions(item),
        "pipeline_run": pipeline_run,
        "blockers": blockers,
        "session": None,
    }


def _started_result(
    started: ExecutionStart, pipeline_run: dict[str, Any], lifecycle_transition: Any
) -> dict[str, Any]:
    item, session = started.item, started.session
    return {
        "status": "started",
        "lifecycle_transition": lifecycle_transition,
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_plan_id": started.plan.id,
        "work_url": _work_item_url(item),
        "coding_url": _coding_work_item_url(item),
        "pipeline_run": pipeline_run,
        "session": {
            "id": session.id,
            "status": session.status,
            "agent_type": session.agent_type,
            "chat_url": f"/chat?session_id={session.id}",
        },
        "workspaces": started.workspaces,
        "blockers": [],
    }


def _work_item_url(item: WorkItem) -> str:
    return f"/chat?area=work&work_item_id={item.id}"


def _coding_work_item_url(item: WorkItem) -> str:
    return f"/chat?area=coding&work_item_id={item.id}"


def _blocked_next_actions(item: WorkItem) -> list[dict[str, str]]:
    return [
        {
            "key": "open_work_item",
            "label": "Open Work Item",
            "url": _work_item_url(item),
        },
        {
            "key": "generate_new_work_plan",
            "label": "Generate a new Work Plan from the latest Jira evidence",
            "url": _work_item_url(item),
        },
    ]
