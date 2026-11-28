"""A teamwork item's gateway session and folder: which item a session is, its contract, idle reason and preparation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from ..records import record_event
from . import RUNNING, item_marker, work_of
from .device_work_state import COORDINATOR_METADATA_KEY, _state, item_branch
from .item_threads import _role_node


def session_item(run: WorkflowRun, session: Any) -> dict[str, Any] | None:
    marker = item_marker(session)
    if marker is None or marker.get("run_id") != run.id:
        return None
    item = _item(run, str(marker["key"]))
    return {**item, "id": str(marker["key"])} if item else None


def item_session_key(run: WorkflowRun, session: Any) -> str | None:
    marker = item_marker(session) if session is not None else None
    return str(marker["key"]) if marker is not None and marker.get("run_id") == run.id else None


def item_idle_reason(run: WorkflowRun, session: Any) -> str | None:
    # An item's session only ever works under its item's contract, never the run's current phase.
    from ..states import STATUS_RUNNING
    from . import session_works_on

    key = item_session_key(run, session)
    if key is None:
        return None
    work = work_of(run)
    item = _item(run, key)
    if not item:
        return f"Item '{key}' is no longer part of the work plan."
    if run.status != STATUS_RUNNING:
        return f"The workflow run is {run.status}; item '{key}' does not go on now."
    if run.current_node_id != work.get("node_id") or work.get("route"):
        return f"The workflow run left the parallel work step; item '{key}' does not go on now."
    if item.get("status") != RUNNING:
        why = f" ({item['reason']})" if item.get("reason") else ""
        return f"Item '{key}' is {item.get('status')}{why}."
    if not session_works_on(run, item, session):
        return f"A newer session works on item '{key}'."
    return None


def coordinator_wake_of(run: WorkflowRun, session: Any) -> bool:
    marker = dict(getattr(session, "metadata_", None) or {}).get(COORDINATOR_METADATA_KEY) if session else None
    work = work_of(run)
    return (isinstance(marker, dict) and marker.get("run_id") == run.id and bool(work)
            and run.current_node_id == work.get("node_id"))


def item_phase_node(run: WorkflowRun, node: PhasedNode, item: dict[str, Any]) -> PhasedNode:
    try:
        from .item_definition import item_node  # type: ignore[attr-defined]
    except ImportError:
        item_node = None
    if item_node is not None:
        return item_node(run, node, item)
    base = _role_node(node, item)
    contract = dict(base.config.get("workflow_contract") or {})
    contract["path_rules"] = {**dict(contract.get("path_rules") or {}), "write": list(item.get("paths") or [])}
    return PhasedNode(id=node.id, kind=NODE_PHASE, title=base.title,
                      config={**base.config, "workflow_contract": contract, "result_values": ["done", "blocked"]})


async def item_contract(db: AsyncSession, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
    work = work_of(run)
    try:
        from .team_block import team_block  # type: ignore[import-not-found]
    except ImportError:  # team_block not available: the same facts without the coordinator's board address
        team_block = None
    if team_block is not None:
        team = await team_block(db, run, item_key=item["id"])
    else:
        team = {"coordinator": work.get("coordinator_hash"), "items": [
            {"id": key, "role": value.get("role"), "status": value.get("status"), "paths": value.get("paths"),
             "agent_hash": value.get("agent_hash"), **({"you": True} if key == item["id"] else {})}
            for key, value in dict(work.get("items") or {}).items() if isinstance(value, dict)]}
    return {"id": item["id"], "title": item.get("title"), "role": item.get("role"),
            "instructions": item.get("instructions"), "paths": list(item.get("paths") or []),
            "proofs": list(item.get("proofs") or []), "depends_on": list(item.get("depends_on") or []),
            "iteration": item.get("iteration"), "shared_contract": work.get("contract"), "team": team}


def _item(run: WorkflowRun, key: str) -> dict[str, Any]:
    return dict(dict(work_of(run).get("items") or {}).get(key) or {})


def _parallel_item_key(run: WorkflowRun, session: Any) -> str | None:
    marker = item_marker(session) if session is not None else None
    if marker is None or marker.get("sequential") or marker.get("run_id") != run.id:
        return None
    return str(marker["key"])


def item_preparation(run: WorkflowRun, session: Any, view: dict[str, Any] | None) -> dict[str, Any] | None:
    # git refuses a branch another worktree has checked out, so each item works on its own branch.
    key = _parallel_item_key(run, session)
    if view is None:
        return view
    if key is None:
        # The main folder: before the run's own first git work there, anything the platform committed beyond the
        # branch's known commit, and any item worktree, is an earlier run's (the launcher cleans it).
        return {**view, "run_commits_on_device": int(_state(run).get("seq") or 0) > 0}
    branched = dict(dict(_state(run).get("branched") or {}).get(key) or {})
    item = _item(run, key)
    return {**view, "branch": branched.get("branch") or item.get("branch") or item_branch(run, key),
            "head": branched.get("head") or item.get("base") or None, "item": key}


async def record_item_preparation(db: AsyncSession, run: WorkflowRun, session: Any,
                                  report: dict[str, Any]) -> str | None:
    # Never the run's own preparation state and never a pause of the run: the scheduler counts the refused job.
    from ..workspace.preparation import EVENT_REPORTED, STATE_NOT_READY, STATE_READY, decide
    from .item_results import note_start_problem

    key = _parallel_item_key(run, session)
    if key is None:
        return None
    outcome = decide(report)
    state = STATE_READY if outcome.ok else STATE_NOT_READY
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": state, "session_id": session.id, "runtime": report.get("runtime"), "for_node": False, "item": key,
        "branch": dict(report.get("branch") or {}).get("state"), "reason": outcome.reason[:500] or None})
    if not outcome.ok:
        note_start_problem(run, key, outcome.reason)
    return state
