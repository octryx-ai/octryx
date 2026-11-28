"""Workflow-run entries of the attention queue: questions, gates, problems and finished runs of the person."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ...time_utils import ensure_utc, utc_now
from ..workflow_runs.states import (
    WAITING_APPROVAL,
    WAITING_AUDIENCE_RECEIPT,
    WAITING_CONFIRMATION,
    WAITING_FUNCTIONAL_ACCEPTANCE,
    WAITING_REPLY,
    WAITING_TOOL_APPROVAL,
    WAITING_WATCH,
)
from .requests import action, run_actions

MAX_RUNS = 50
DONE_WITHIN = timedelta(hours=72)
_GATE_KINDS = (WAITING_CONFIRMATION, WAITING_APPROVAL, WAITING_TOOL_APPROVAL, WAITING_FUNCTIONAL_ACCEPTANCE,
               WAITING_AUDIENCE_RECEIPT)


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


async def run_context(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ..workflow_runs.records import main_session_id

    workspace = await db.get(Project, run.project_id) if run.project_id else None
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    return {
        "workspace": {"id": workspace.id, "name": workspace.name} if workspace is not None else None,
        "run": {"id": run.id, "workflow_key": run.workflow_key, "title": run.title},
        "work_item": {"id": item.id, "key": item.source_key, "title": item.title} if item is not None else None,
        "session_id": await main_session_id(db, run),
    }


async def _node_title(db: AsyncSession, run: WorkflowRun) -> str:
    from ..workflow_runs.views import run_nodes

    try:
        nodes = await run_nodes(db, run, user=None)
    except Exception:  # noqa: BLE001 - a run of an unpublished flow still lists
        nodes = []
    node = next((item for item in nodes if item["id"] == run.current_node_id), None)
    return str((node or {}).get("title") or run.current_node_id or "")


def _link(context: dict[str, Any]) -> dict[str, str]:
    session_id = context.get("session_id")
    return ({"href": f"/chat?session_id={session_id}", "label": "Open the run"} if session_id
            else {"href": "/chat?area=work", "label": "Open Work"})


def _kind(run: WorkflowRun) -> str | None:
    if run.status == "paused":
        return "problem"
    if run.waiting_kind == WAITING_REPLY:
        return "question"
    if run.waiting_kind in _GATE_KINDS:
        return "gate"
    if run.waiting_kind == WAITING_WATCH and dict(run.pull_request or {}).get("reviewer_skipped"):
        return "done"
    return None


def _text(run: WorkflowRun, kind: str) -> str:
    state = dict(run.node_state or {})
    if kind == "problem":
        pause = dict(state.get("pause") or {})
        from ..workflow_runs.limits import pause_message

        return pause_message(run, str(run.pause_reason or ""), pause)
    waiting = dict(state.get("waiting") or {})
    if kind == "done":
        return "The pull request is open and waits for your review and merge."
    return str(waiting.get("question") or waiting.get("title") or waiting.get("subject") or "Your decision lets the "
               "run go on.").replace("_", " ")


async def run_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from ..workflow_runs.access import run_access
    from ..workflow_runs.actions import available_actions

    rows = (await db.execute(select(WorkflowRun).where(
        or_(WorkflowRun.requested_by == user.id, WorkflowRun.responsible_user_id == user.id),
        WorkflowRun.status.in_(("paused", "waiting")),
    ).order_by(WorkflowRun.updated_at.desc()).limit(MAX_RUNS))).scalars().all()
    entries: list[dict[str, Any]] = []
    for run in rows:
        kind = _kind(run)
        if kind is None:
            continue  # waiting for a device or an external state: the run is working, not waiting for a person
        own = run.requested_by == user.id
        offered = await available_actions(db, run, access="write" if own else await run_access(db, run, user),
                                          user=user)
        waiting = dict(dict(run.node_state or {}).get("waiting") or {})
        actions = run_actions(run.id, offered, payload_hash=waiting.get("payload_hash"))
        if not own and not actions:
            continue  # responsible, but nothing of this state is theirs to decide (four-eyes, a pause)
        context = await run_context(db, run)
        pause = dict(dict(run.node_state or {}).get("pause") or {})
        title = run.title
        if run.pause_reason == "loop_detected":
            # The phone push shows the title: it says what happened and how often.
            title = (f"Loop detected, {run.title} paused: {pause.get('item')} dispatched {pause.get('count')}× "
                     f"in {pause.get('window_minutes')} min")
        entries.append({
            "key": f"run:{run.id}:{run.updated_at.isoformat() if run.updated_at else ''}", "kind": kind,
            "id": run.id, "title": title, "subtitle": await _node_title(db, run),
            "text": _text(run, kind), "created_at": _iso(run.updated_at),
            "severity": {"problem": "warning", "done": "info"}.get(kind, "action"),
            "code": pause.get("code") or run.pause_reason, **context, "link": _link(context),
            "actions": actions,
        })
    return entries


async def finished_entries(db: AsyncSession, user: User, dismissed: set[str]) -> list[dict[str, Any]]:
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.requested_by == user.id, WorkflowRun.status == "completed",
        WorkflowRun.completed_at >= (utc_now() - DONE_WITHIN).replace(tzinfo=None),
    ).order_by(WorkflowRun.completed_at.desc()).limit(MAX_RUNS))).scalars().all()
    entries: list[dict[str, Any]] = []
    for run in rows:
        key = f"done:{run.id}"
        if key in dismissed:
            continue
        context = await run_context(db, run)
        pr = dict(run.pull_request or {})
        url = pr.get("url") if str(pr.get("url") or "").startswith(("https://", "http://")) else None
        entries.append({
            "key": key, "kind": "done", "id": run.id, "title": run.title, "subtitle": run.outcome or "completed",
            "text": f"Finished ({run.outcome or 'completed'})." + (" Pull request: " + url if url else ""),
            "created_at": _iso(run.completed_at), "severity": "info", **context,
            "link": {"href": url, "label": "Open the pull request"} if url else _link(context),
            "actions": [action("dismiss", "Done", path="/api/v1/attention/dismiss", body={"key": key},
                               tone="primary")],
        })
    return entries


__all__ = ["finished_entries", "run_context", "run_entries"]
