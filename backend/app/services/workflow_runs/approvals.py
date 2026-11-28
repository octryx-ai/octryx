"""A decided approval moves the run that waits for it (run approvals and tool approvals)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, WorkflowRun
from .limits import pause_run
from .records import lock_run
from .states import PAUSE_APPROVAL_TIMEOUT, STATUS_RUNNING, STATUS_WAITING, WAITING_TOOL_APPROVAL


async def _waiting_tool_run(db: AsyncSession, approval: Approval) -> WorkflowRun | None:
    runs = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.status == STATUS_WAITING, WorkflowRun.waiting_kind == WAITING_TOOL_APPROVAL,
    ))).scalars().all()
    return next((run for run in runs
                 if dict(dict(run.node_state or {}).get("waiting") or {}).get("approval_id") == approval.id), None)


async def on_approval_decided(db: AsyncSession, approval: Approval) -> None:
    from .watch import deliver_event
    from .watch_events import APPROVAL_DECIDED, WatchEvent

    await deliver_event(db, WatchEvent(APPROVAL_DECIDED, approval_id=approval.id), source="approval")
    if (approval.action or "").startswith("workflow_run.approval"):
        from .hitl_decisions import approval_decided

        await approval_decided(db, approval)
        return
    run = await _waiting_tool_run(db, approval)
    if run is None:
        return
    run = await lock_run(db, run)
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    if (run.status != STATUS_WAITING or run.waiting_kind != WAITING_TOOL_APPROVAL
            or waiting.get("approval_id") != approval.id):
        return  # decided twice, or the run moved on meanwhile: the action never runs twice
    if waiting.get("side_effect"):
        from .failure import resume_side_effect

        await resume_side_effect(db, run, approval)
        return
    from .engine import rerun_current_node, resolve_current_node

    if approval.status == "approved":
        run.status, run.waiting_kind = STATUS_RUNNING, None
        await rerun_current_node(db, run, actor_id=approval.approved_by)
    elif approval.status == "expired":
        await pause_run(db, run, reason=PAUSE_APPROVAL_TIMEOUT, actor_id=None, detail={
            "message": "the tool approval was not decided in time", "resume": {"kind": "rerun"},
        })
    else:
        from .action_failures import record_failure
        from .platform.dispatch import CLASS_REJECTED

        # The requester refused the step: a pause node never asks them again, the run takes its failure route.
        record_failure(run, node_id=run.current_node_id or "", action=str(waiting.get("action") or ""),
                       reason="the tool approval was rejected", failure_class=CLASS_REJECTED)
        await resolve_current_node(db, run, "failed", actor_id=approval.approved_by)


__all__ = ["on_approval_decided"]
