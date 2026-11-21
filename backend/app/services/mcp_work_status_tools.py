"""Approvals and run lists over MCP, under the platform's own read rules (C-MCP).

- ``approval_get(approval_id)``: one approval, readable exactly when
  ``services/approval/access.require_approval_visible`` allows it. That covers a session reader, a
  task run's owner or starter, a governance review's requester or reviewer, and a global admin.
  Anything else answers like an unknown id.
- ``product_run_list``: the connection Workspace's newest workflow runs and scheduled task runs the caller may
  read; chat turns only on ``include_chat_turns``.

Each answer carries closed facts only. Tool arguments and results are never read.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, User
from ..models.runtime.product_run import RUN_ORIGIN_CHAT_TURN, RUN_ORIGIN_SUB_AGENT, ProductRun
from ..models.runtime.workflow_run import WorkflowRun
from .approval.access import require_approval_visible
from .mcp_governed_knowledge import McpCaller
from .session.resource_access import require_record_access
from .workflow_runs.access import run_access

MAX_LISTED_RUNS = 20
_SCAN_RUNS = 100
_NOT_FOUND = {"state": "not_found", "reason": "not_found"}


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def approval_view(approval: Approval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "action": approval.action,
        "status": approval.status,
        "reason": approval.reason,
        "session_id": approval.session_id,
        "task_run_id": approval.task_run_id,
        "workspace_id": approval.workspace_id,
        "created_at": _timestamp(approval.created_at),
        "resolved_at": _timestamp(approval.resolved_at),
    }


async def mcp_approval_get(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    del caller, workspace_id
    approval_id = str(arguments.get("approval_id") or "").strip()[:36]
    try:
        approval = await require_approval_visible(db, approval=await db.get(Approval, approval_id), user_id=user.id)
    except HTTPException:
        return dict(_NOT_FOUND)
    return {"state": "ok", "approval": approval_view(approval)}


async def _readable_run(db: AsyncSession, run: ProductRun | None, *, user: User, workspace_id: str) -> bool:
    if run is None or run.workspace_id != workspace_id:
        return False
    try:
        await require_record_access(db, run, user_id=user.id, not_found_detail="Product run not found")
    except HTTPException:
        return False
    return True


def _listed_turn_filter(arguments: dict[str, Any]) -> list[Any]:
    """Which Product Runs the list leaves out unless ``include_chat_turns`` asks for them.

    Asked to summarise the latest workflow run, a model would otherwise find the chat's own turn as the newest
    Product Run (still running while it calls this tool) and summarise it as "the latest run" instead of the
    person's workflow run; with only the own turn hidden, it summarises another session's chat turn instead.
    Chat turns and sub-agent child turns are conversation, not runs the person started: by default only the
    workflow runs (``workflow_runs``) and scheduled task runs are listed.
    ``include_chat_turns`` lists every turn, the calling chat's own included.
    """
    if arguments.get("include_chat_turns") is True:
        return []
    return [ProductRun.origin.notin_((RUN_ORIGIN_CHAT_TURN, RUN_ORIGIN_SUB_AGENT))]


async def _workflow_runs(db: AsyncSession, *, user: User, workspace_id: str) -> list[dict[str, Any]]:
    """The Workspace's workflow runs the person may read, newest first (``workflow_runs.access.run_access``)."""
    rows = (
        await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == workspace_id)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(_SCAN_RUNS)
        )
    ).scalars().all()
    listed: list[dict[str, Any]] = []
    for run in rows:
        if len(listed) >= MAX_LISTED_RUNS:
            break
        if await run_access(db, run, user) == "none":
            continue
        listed.append({
            "id": run.id,
            "workflow_key": run.workflow_key,
            "title": run.title,
            "status": run.status,
            "outcome": run.outcome,
            "ticket_key": run.ticket_key,
            "started_by_you": run.requested_by == user.id,
            "created_at": _timestamp(run.created_at),
            "completed_at": _timestamp(run.completed_at),
        })
    return listed


async def mcp_product_run_list(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """The person's workflow runs first, then scheduled task runs (chat turns on request), each newest first."""
    rows = (
        (
            await db.execute(
                select(ProductRun)
                .where(ProductRun.workspace_id == workspace_id, *_listed_turn_filter(arguments or {}))
                .order_by(ProductRun.created_at.desc())
                .limit(_SCAN_RUNS)
            )
        )
        .scalars()
        .all()
    )
    runs = []
    for run in rows:
        if len(runs) >= MAX_LISTED_RUNS:
            break
        if await _readable_run(db, run, user=user, workspace_id=workspace_id):
            runs.append(
                {
                    "id": run.id,
                    "session_id": run.session_id,
                    "origin": run.origin,
                    "state": run.state,
                    "end_reason": run.end_reason,
                    "attempt_count": run.attempt_count,
                    "created_at": _timestamp(run.created_at),
                }
            )
    workflow_runs = await _workflow_runs(db, user=user, workspace_id=workspace_id)
    return {"state": "ok", "workspace_id": workspace_id, "workflow_runs": workflow_runs, "runs": runs,
            "count": len(runs)}


__all__ = ["approval_view", "mcp_approval_get", "mcp_product_run_list"]
