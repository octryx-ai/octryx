"""One Claude Code session per phase node: which session a pass resumes and how an ended pass is remembered."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from .continuation_marker import STATE_STARTED, _marker

SESSION_KEY = "device_phase_session"


# Per phase node, so a phase resumes its own session after other phases ran in between.
SESSIONS_KEY = "device_phase_sessions"


SESSION_EPIC = "epic"
RESUME_PHASE = "phase"
RESUME_EPIC = "epic"


async def _pass_session(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    from ....models import DeviceJob

    marker = _marker(run)
    if marker.get("state") != STATE_STARTED or not marker.get("phase") or not marker.get("job_id"):
        return None
    job = await db.get(DeviceJob, str(marker["job_id"]))
    if job is None:
        return None
    return {"node_id": marker.get("node_id"), "job_id": job.id, "turn_id": marker.get("turn_id") or job.turn_id,
            "claude_session_id": _job_session(job), "device_id": job.device_id, "folder": job.folder,
            "profile": job.profile}


async def _remember_phase_session(db: AsyncSession, run: WorkflowRun) -> None:
    # Runtime steps leave the remembered session alone: a red pipeline returns to the phase whose session it continues.
    entry = await _pass_session(db, run)
    if entry is None:
        return
    context = dict(run.context or {})
    sessions = {**dict(context.get(SESSIONS_KEY) or {}), str(entry["node_id"]): entry}
    run.context = {**context, SESSION_KEY: entry, SESSIONS_KEY: sessions}


def _job_session(job: Any) -> str:
    resumed = str(job.resume_claude_session_id or "")
    return str(job.claude_session_id or "") or ("" if resumed.startswith("fork:") else resumed)


def _node_session(run: WorkflowRun, node_id: str) -> dict[str, Any]:
    context = dict(run.context or {})
    entry = dict(dict(context.get(SESSIONS_KEY) or {}).get(node_id) or {})
    if entry:
        return entry
    last = dict(context.get(SESSION_KEY) or {})
    return last if last.get("node_id") == node_id else {}


async def _session_here(db: AsyncSession, entry: dict[str, Any], target: dict[str, Any]) -> str:
    from ....models import DeviceJob
    from ...devices.dispatch_gate import normalized_folder
    from ...devices.engine_state import resumable_from_snapshot

    if not entry:
        return ""
    here = (str(target.get("device_id") or ""), normalized_folder(target.get("folder")),
            str(target.get("profile") or ""))
    session = str(entry.get("claude_session_id") or "")
    job = await db.get(DeviceJob, str(entry["job_id"])) if entry.get("job_id") else None
    if not session and job is not None and job.turn_id == entry.get("turn_id"):
        # The device reported the session id only after the pass ended: the job still names it while no other turn
        # ran on it since.
        session = _job_session(job)
    if (entry.get("device_id"), entry.get("folder"), entry.get("profile")) == here:
        return session
    # Another target continues the session only from the files the platform holds.
    return await resumable_from_snapshot(db, job.session_id, session) if job is not None else ""


async def _epic_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode, target: dict[str, Any]) -> str:
    if str(dict(node.config or {}).get("session") or "") != SESSION_EPIC:
        return ""
    from ..epic_chain import CHAIN_KEY

    previous_id = str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    previous = await db.get(WorkflowRun, previous_id) if previous_id and previous_id != run.id else None
    if previous is None:
        return ""
    entry = _node_session(previous, node.id)
    if not entry:
        last = await _pass_session(db, previous)
        entry = last if last is not None and last.get("node_id") == node.id else {}
    return await _session_here(db, entry, target)


async def _resumable_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode,
                             target: dict[str, Any]) -> tuple[str, str]:
    if node.kind != NODE_PHASE:
        return "", ""
    from .run_session import shared_run_session

    shared = await shared_run_session(db, run, node, target)
    if shared[0]:
        return shared
    own = await _session_here(db, _node_session(run, node.id), target)
    if own:
        return own, RESUME_PHASE
    epic = await _epic_session(db, run, node, target)
    return (epic, RESUME_EPIC) if epic else ("", "")


async def _remember_ended_pass(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any]) -> None:
    # Remembered now: by the next phase entry, teamwork's git turns have reused the job and the session is lost.
    from ....models import DeviceJob

    job = await db.get(DeviceJob, str(marker.get("job_id") or ""))
    if job is not None and (not marker.get("turn_id") or job.turn_id == marker.get("turn_id")):
        await _remember_phase_session(db, run)
