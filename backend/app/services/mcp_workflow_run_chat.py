"""A platform chat's side of the MCP workflow run tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, User, WorkflowRun
from .mcp_workflow_run_session import _contract
from .workflow_runs.octryx.attach import active_run_of_item, work_item_in_workspace
from .workflow_runs.records import active_run_for_session


async def _chat_follow(db: AsyncSession, *, chat: Session, user: User, workspace_id: str, run_id: str,
                       reference: str) -> dict[str, Any]:
    # Requester only, like ``POST /workflow-runs/{id}/sessions``.
    from .workflow_runs.access import run_access
    from .workflow_runs.records import bind_session

    run = await db.get(WorkflowRun, run_id) if run_id else None
    if not run_id:
        item = await work_item_in_workspace(db, reference, workspace_id)
        run = await active_run_of_item(db, item) if item is not None else None
        if run is None:
            return {"state": "needs_clarification", "reason": "no_active_run",
                    "message": "The Work item has no active run; start one with start_workflow."}
    if run is None or run.project_id != workspace_id or await run_access(db, run, user) == "none":
        return {"state": "not_found", "reason": "unknown_run"}
    if run.requested_by != user.id:
        return {"state": "denied", "reason": "not_requester",
                "message": "Only the run's requester continues it in their chat."}
    current = await active_run_for_session(db, chat.id)
    if current is None or current.id != run.id:
        await bind_session(db, run, chat, actor_id=user.id)
    return {"state": "selected", "workflow_run": await _contract(db, run, user, chat)}


MAX_RECENT_RUNS = 5
_SCAN_RECENT_RUNS = 50


async def _recent_runs(db: AsyncSession, *, user: User, workspace_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from .workflow_runs.access import run_access

    rows = (await db.execute(select(WorkflowRun).where(WorkflowRun.project_id == workspace_id,
                                                       WorkflowRun.parent_run_id.is_(None))
                             .order_by(WorkflowRun.created_at.desc()).limit(_SCAN_RECENT_RUNS))).scalars().all()
    runs: list[dict[str, Any]] = []
    for run in rows:
        if len(runs) >= MAX_RECENT_RUNS:
            break
        if await run_access(db, run, user) != "none":
            runs.append({"run_id": run.id, "workflow_key": run.workflow_key, "title": run.title,
                         "status": run.status, "work_item": run.ticket_key,
                         "started_at": run.created_at.isoformat() if run.created_at else None})
    return runs


async def _chat_without_run(db: AsyncSession, *, user: User, workspace_id: str) -> dict[str, Any]:
    # A successful lookup, not a refusal status: a model would read a refusal as a broken connection.
    recent = await _recent_runs(db, user=user, workspace_id=workspace_id)
    message = "No workflow run is running in this chat: none was started or continued here."
    message += (" The Workspace's most recent runs are listed in recent_runs; workflow_run_status with a run_id "
                "reads one." if recent else " This Workspace has no workflow runs you can see.")
    return {"state": "ok", "reason": "no_run_bound", "workflow_run": None, "message": message,
            "recent_runs": recent, "start_hint": "start_workflow starts a run after the person confirms it."}
