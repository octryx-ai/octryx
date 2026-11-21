"""The companion's job list and read-only watch view (Octryx companion, "watch, team and handovers").

- ``scope=mine``: the person's runs; ``scope=team``: the runs of the Workspaces they are a member of (Work scope).
- A watcher sees the run's phases, its current step and its run events. Nothing from a device's folders or chat
  stream is shown (device text streams stay in the owner's chat).
- ``can_control`` is decided here: only the run's requester controls it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun, WorkflowRunEvent
from ...time_utils import ensure_utc, utc_now
from .event_text import event_text
from .running import run_state

MAX_JOBS = 50
MAX_EVENTS = 50
RECENT = timedelta(hours=24)
SCOPES = ("mine", "team")


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _target(run: WorkflowRun, *, own: bool) -> dict[str, Any] | None:
    from ..workflow_runs.runtime_target.target import target_view

    view = target_view(run)
    if view is None:
        return None
    keys = ("kind", "label", "profile", "reason", "device_name", "online") + (("folder",) if own else ())
    if not own and view.get("kind") == "device":
        view = {**view, "label": f"{view.get('device_name') or 'a device'} ({view.get('profile') or ''})"}
    return {key: view[key] for key in keys if key in view}


async def _phases(db: AsyncSession, run: WorkflowRun) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The run's phases with ``done`` | ``active`` | ``problem`` | ``pending``: a phase before the current node
    (in display order) is done, also while the run waits between phases (e.g. at a confirmation)."""
    from ..workflow_runs.views import run_nodes

    try:
        nodes = await run_nodes(db, run, user=None)
    except Exception:  # noqa: BLE001 - a run of an unpublished flow still lists
        nodes = []
    order = [node["id"] for node in nodes]
    current = next((node for node in nodes if node["id"] == run.current_node_id), None)
    position = order.index(current["id"]) if current is not None else -1
    states = []
    for node in (node for node in nodes if node["kind"] == "phase"):
        at = order.index(node["id"])
        if run.status == "completed" or at < position:
            state = "done"
        elif at == position and run.status in ("running", "waiting", "paused"):
            state = "problem" if run.status == "paused" else "active"
        else:
            state = "pending"
        states.append({"id": node["id"], "title": node.get("title") or node["id"], "state": state})
    return states, ({"id": current["id"], "title": current.get("title") or current["id"],
                     "kind": current.get("kind")} if current else None)


async def _owner(db: AsyncSession, user_id: str) -> dict[str, str]:
    user = await db.get(User, user_id)
    return {"id": user_id, "name": (user.display_name or user.username) if user is not None else ""}


async def job_row(db: AsyncSession, run: WorkflowRun, viewer: User) -> dict[str, Any]:
    from .run_items import run_context

    phases, current = await _phases(db, run)
    context = await run_context(db, run)
    index = next((i for i, phase in enumerate(phases) if phase["state"] in ("active", "problem")), None)
    if index is None:  # between phases: the last phase done is where the run stands
        done = [i for i, phase in enumerate(phases) if phase["state"] == "done"]
        index = done[-1] if done and run.status != "completed" else None
    own = run.requested_by == viewer.id
    return {
        "run_id": run.id, "title": run.title, "workflow_key": run.workflow_key, "work_item": context["work_item"],
        "workspace": context["workspace"], "owner": await _owner(db, run.requested_by), "state": run_state(run),
        "status": run.status, "current_node": current, "phase_index": index + 1 if index is not None else None,
        "phase_count": len(phases), "since": _iso(run.updated_at), "runtime_target": _target(run, own=own),
        "can_control": own,
    }


async def job_list(db: AsyncSession, viewer: User, *, scope: str, workspace_id: str | None) -> list[dict[str, Any]]:
    from ..secure_work.access import work_scope_project_ids

    since = (utc_now() - RECENT).replace(tzinfo=None)
    query = select(WorkflowRun).where(or_(WorkflowRun.status.in_(("running", "waiting", "paused")),
                                          WorkflowRun.updated_at >= since))
    if scope == "team":
        allowed = await work_scope_project_ids(db, viewer)  # None: a platform admin sees every Workspace
        if workspace_id:
            if allowed is not None and workspace_id not in allowed:
                return []
            query = query.where(WorkflowRun.project_id == workspace_id)
        elif allowed is not None:
            query = query.where(WorkflowRun.project_id.in_(tuple(allowed) or ("",)))
    else:
        query = query.where(WorkflowRun.requested_by == viewer.id)
        if workspace_id:
            query = query.where(WorkflowRun.project_id == workspace_id)
    rows = (await db.execute(query.order_by(WorkflowRun.updated_at.desc()).limit(MAX_JOBS))).scalars().all()
    return [await job_row(db, run, viewer) for run in rows]


async def job_detail(db: AsyncSession, run: WorkflowRun, viewer: User) -> dict[str, Any]:
    from ..workflow_runs.views import run_nodes

    row = await job_row(db, run, viewer)
    phases, _current = await _phases(db, run)
    try:
        titles = {node["id"]: node.get("title") or node["id"] for node in await run_nodes(db, run, user=None)}
    except Exception:  # noqa: BLE001
        titles = {}
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id)
                               .order_by(WorkflowRunEvent.created_at.desc()).limit(MAX_EVENTS))).scalars().all()
    texts = []
    for event in events:
        text, technical = event_text(event, titles)
        texts.append({"text": text, "kind": event.kind, "technical": technical, "at": _iso(event.created_at)})
    current = next((item for item in texts if not item["technical"]), texts[0] if texts else None)
    problem, actions = None, []
    if run.status == "paused":
        pause = dict(dict(run.node_state or {}).get("pause") or {})
        problem = {"reason": run.pause_reason or "", "code": str(pause.get("code") or run.pause_reason or ""),
                   "message": str(pause.get("message") or "")}
    if row["can_control"] and run.status in ("running", "waiting", "paused"):
        from ..workflow_runs.actions import available_actions
        from .requests import run_actions

        waiting = dict(dict(run.node_state or {}).get("waiting") or {})
        actions = run_actions(run.id, await available_actions(db, run, access="write", user=viewer),
                              payload_hash=waiting.get("payload_hash"))
    return {**row, "phases": phases, "current_step": current, "events": texts, "problem": problem,
            "actions": actions}


__all__ = ["SCOPES", "job_detail", "job_list", "job_row"]
