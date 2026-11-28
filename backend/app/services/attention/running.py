"""The person's runs for the companion's arms: up to eight, with a state the UI colours."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...time_utils import ensure_utc, utc_now
from ..workflow_runs.states import (
    WAITING_APPROVAL,
    WAITING_AUDIENCE_RECEIPT,
    WAITING_CONFIRMATION,
    WAITING_FUNCTIONAL_ACCEPTANCE,
    WAITING_REPLY,
    WAITING_TOOL_APPROVAL,
)

MAX_RUNNING = 8
RECENT_DONE = timedelta(hours=24)
_NEEDS_YOU = frozenset({WAITING_REPLY, WAITING_CONFIRMATION, WAITING_APPROVAL, WAITING_TOOL_APPROVAL,
                        WAITING_FUNCTIONAL_ACCEPTANCE, WAITING_AUDIENCE_RECEIPT})


def run_state(run: WorkflowRun) -> str:
    if run.status == "paused":
        return "problem"
    if run.status == "completed":
        return "done"
    if run.status in ("stopped", "failed"):
        return "problem"
    if run.status == "waiting" and run.waiting_kind in _NEEDS_YOU:
        return "needs_you"
    return "working"


async def running_runs(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from ..workflow_runs.graph import graph_for_run
    from ..workflow_runs.records import main_session_id
    from ..workflow_runs.runtime_target.target import target_view
    from .run_items import run_context

    since = (utc_now() - RECENT_DONE).replace(tzinfo=None)
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.requested_by == user.id,
        or_(WorkflowRun.status.in_(("running", "waiting", "paused")),
            (WorkflowRun.status == "completed") & (WorkflowRun.completed_at >= since)),
    ).order_by(WorkflowRun.updated_at.desc()).limit(MAX_RUNNING * 2))).scalars().all()
    active = [run for run in rows if run.status != "completed"]
    chosen = (active + [run for run in rows if run.status == "completed"])[:MAX_RUNNING]
    runs = []
    for run in chosen:
        node = None
        if run.current_node_id:
            try:
                graph_node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
            except Exception:  # noqa: BLE001 - a run of an unpublished flow still shows
                graph_node = None
            node = {"id": run.current_node_id, "title": getattr(graph_node, "title", "") or run.current_node_id,
                    "kind": getattr(graph_node, "kind", "")}
        context = await run_context(db, run)
        runs.append({
            "id": run.id, "workflow_key": run.workflow_key, "title": run.title, "status": run.status,
            "state": run_state(run), "current_node": node, "runtime_target": target_view(run),
            "work_item": context["work_item"], "workspace": context["workspace"],
            # what the companion shows first and why a waiting run waits (never "Working" for a wait)
            "ticket_key": (context["work_item"] or {}).get("key"),
            "waiting_kind": run.waiting_kind if run.status == "waiting" else None,
            "pause_reason": run.pause_reason if run.status == "paused" else None,
            "session_id": context["session_id"] or await main_session_id(db, run),
            "updated_at": ensure_utc(run.updated_at).isoformat() if run.updated_at else None,
        })
    return runs


__all__ = ["MAX_RUNNING", "run_state", "running_runs"]
