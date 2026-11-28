"""A Secure Work coding execution is a workflow run for the Work item (an approved Work Plan first): the bug workflow
for a bug, the delivery workflow otherwise; the run's phases enforce the tests and evidence."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, User, WorkItem
from ...workflow_runs.records import WorkflowRunError, new_chat_session, start_run, ticket_key_of
from ...workflow_runs.triage_routing import DEFAULT_ROUTES
from ..jira_values import blank_to_none
from ..lifecycle_transitions import STATE_DEVELOPMENT, auto_transition_work_item
from .execution_scope import _approved_plan, _get_work_item
from .pipeline_execution_context import _apply_pipeline_work_item_state, _stale_plan_blocker

BUG_TYPES = frozenset({"bug", "defect"})


def coding_workflow_for(item: WorkItem) -> str:
    kind = "bug" if str(item.issue_type or "").strip().lower() in BUG_TYPES else "feature"
    return DEFAULT_ROUTES[kind]


async def start_work_item_coding_agent_execution(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    plan = await _approved_plan(db, item, blank_to_none(payload.get("change_plan_id")))
    if plan is None:
        raise HTTPException(status_code=409, detail="Approved Work Plan required before agent execution can start")
    stale = _stale_plan_blocker(item, plan)
    if stale is not None:  # the source changed after the plan was approved: re-plan, start nothing
        return _blocked(db, item, plan, stale, current_user)
    workflow_key = coding_workflow_for(item)
    session = await new_chat_session(db, current_user, item.project_id)
    try:
        run = await start_run(db, user=current_user, workflow_key=workflow_key, project_id=item.project_id,
                              work_item_id=item.id, session=session, ticket_key=ticket_key_of(item),
                              context={"work_change_plan_id": plan.id})
    except WorkflowRunError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from error
    lifecycle_transition = await auto_transition_work_item(
        db, item=item, current_user=current_user, to_state=STATE_DEVELOPMENT,
        reason=f"Coding started as workflow run {run.id} ({workflow_key}).")
    await db.commit()
    return {
        "status": "started",
        "lifecycle_transition": lifecycle_transition,
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_plan_id": plan.id,
        "work_url": f"/chat?area=work&work_item_id={item.id}",
        "coding_url": f"/chat?area=coding&work_item_id={item.id}",
        "workflow_run": {"id": run.id, "workflow_key": workflow_key, "status": run.status},
        "session": {"id": session.id, "status": session.status, "chat_url": f"/chat?session_id={session.id}"},
        "blockers": [],
    }


def _blocked(db: AsyncSession, item: WorkItem, plan: Any, blocker: dict[str, Any], user: User) -> dict[str, Any]:
    _apply_pipeline_work_item_state(db, item, execution_context={"blockers": [blocker]}, current_user=user)
    db.add(AuditLog(user_id=user.id, action="secure_work.coding_agent_execution_blocked",
                    resource_type="secure_work_coding_execution", resource_id=item.id, project_id=item.project_id,
                    details={"work_item_id": item.id, "source_key": item.source_key, "change_plan_id": plan.id,
                             "blockers": [blocker]}))
    work_url = f"/chat?area=work&work_item_id={item.id}"
    return {"status": "blocked", "reason": blocker["code"], "work_item_id": item.id, "source_key": item.source_key,
            "change_plan_id": plan.id, "work_url": work_url, "coding_url": f"/chat?area=coding&work_item_id={item.id}",
            "next_actions": [{"key": "open_work_item", "label": "Open Work Item", "url": work_url},
                             {"key": "generate_new_work_plan",
                              "label": "Generate a new Work Plan from the latest source evidence", "url": work_url}],
            "workflow_run": None, "session": None, "blockers": [blocker]}


__all__ = ["coding_workflow_for", "start_work_item_coding_agent_execution"]
