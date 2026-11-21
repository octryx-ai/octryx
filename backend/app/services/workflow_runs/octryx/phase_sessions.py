"""One Claude Code session per phase node: which session a pass resumes and how an ended pass is remembered."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from .continuation_marker import STATE_STARTED, _marker

#: The Claude Code session of the run's last phase pass on the device: ``node_id``, ``job_id``, ``turn_id``,
#: ``claude_session_id``, ``device_id``, ``folder``, ``profile`` (also :func:`_node_session`'s fallback when
#: SESSIONS_KEY has no entry for the node).
SESSION_KEY = "device_phase_session"


#: The same per phase node (``{node_id: session}``): the next pass of a phase resumes its own session, also after
#: other phases ran in between.
SESSIONS_KEY = "device_phase_sessions"


#: ``config.session`` of a phase that also resumes its session of the epic's previous story.
SESSION_EPIC = "epic"
RESUME_PHASE = "phase"
RESUME_EPIC = "epic"


async def _pass_session(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    """The session of the pass that is ending (the current continuation marker) when it was a phase turn."""
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
    """The pass that is ending was a phase turn: remember its session, under its phase node.

    Runtime steps (``workspace.prepare``, the pipeline) leave it as it is: a red pipeline sends the run back to the
    phase whose session it continues. With only one remembered session, a
    loop from the pipeline back to ``backend`` after ``frontend`` and ``tests`` ran started ``backend`` fresh."""
    entry = await _pass_session(db, run)
    if entry is None:
        return
    context = dict(run.context or {})
    sessions = {**dict(context.get(SESSIONS_KEY) or {}), str(entry["node_id"]): entry}
    run.context = {**context, SESSION_KEY: entry, SESSIONS_KEY: sessions}


def _job_session(job: Any) -> str:
    """The Claude Code session the job's turn runs in: the one it reported, else the one it resumes (a resumed pass
    keeps its session even before the device reported it again)."""
    resumed = str(job.resume_claude_session_id or "")
    return str(job.claude_session_id or "") or ("" if resumed.startswith("fork:") else resumed)


def _node_session(run: WorkflowRun, node_id: str) -> dict[str, Any]:
    """The remembered session of ``node_id`` in ``run`` (the per-node map, else the run's single entry)."""
    context = dict(run.context or {})
    entry = dict(dict(context.get(SESSIONS_KEY) or {}).get(node_id) or {})
    if entry:
        return entry
    last = dict(context.get(SESSION_KEY) or {})
    return last if last.get("node_id") == node_id else {}


async def _session_here(db: AsyncSession, entry: dict[str, Any], target: dict[str, Any]) -> str:
    """``entry``'s Claude Code session when it ran on the target's device, folder and profile; else ``""``."""
    from ....models import DeviceJob
    from ...devices.dispatch_gate import normalized_folder

    if not entry:
        return ""
    here = (str(target.get("device_id") or ""), normalized_folder(target.get("folder")),
            str(target.get("profile") or ""))
    if (entry.get("device_id"), entry.get("folder"), entry.get("profile")) != here:
        return ""
    session = str(entry.get("claude_session_id") or "")
    if not session and entry.get("job_id"):
        # The device reported the session id only after the pass ended: the job still names it while no other turn
        # ran on it since.
        job = await db.get(DeviceJob, str(entry["job_id"]))
        if job is not None and job.turn_id == entry.get("turn_id"):
            session = _job_session(job)
    return session


async def _epic_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode, target: dict[str, Any]) -> str:
    """The session of the same phase in the epic's previous story run (``context.epic_chain.after_run``), when the
    phase asks for it (``config.session: "epic"``) and it ran on the same device, folder and profile."""
    if str(dict(node.config or {}).get("session") or "") != SESSION_EPIC:
        return ""
    from ..epic_chain import CHAIN_KEY

    previous_id = str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    previous = await db.get(WorkflowRun, previous_id) if previous_id and previous_id != run.id else None
    if previous is None:
        return ""
    entry = _node_session(previous, node.id)
    if not entry:  # the previous story's last pass of this phase that nothing remembered yet
        last = await _pass_session(db, previous)
        entry = last if last is not None and last.get("node_id") == node.id else {}
    return await _session_here(db, entry, target)


async def _resumable_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode,
                             target: dict[str, Any]) -> tuple[str, str]:
    """``(Claude Code session, why)`` this pass resumes: the phase's own earlier pass in this run on the same device,
    folder and profile (``RESUME_PHASE``), else for an epic phase its pass in the previous story (``RESUME_EPIC``);
    ``("", "")`` for a fresh session."""
    if node.kind != NODE_PHASE:
        return "", ""
    from .run_session import shared_run_session

    shared = await shared_run_session(db, run, node, target)  # the run's class shares one session across phases
    if shared[0]:
        return shared
    own = await _session_here(db, _node_session(run, node.id), target)
    if own:
        return own, RESUME_PHASE
    epic = await _epic_session(db, run, node, target)
    return (epic, RESUME_EPIC) if epic else ("", "")


async def _remember_ended_pass(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any]) -> None:
    """The phase turn that just ended is remembered under its phase now, while its job still names its session.

    Remembered only when the next phase is entered, the plan pass is lost: by then teamwork's git work has run fresh
    turns on the same job, so the replan finds no session and starts a new one."""
    from ....models import DeviceJob

    job = await db.get(DeviceJob, str(marker.get("job_id") or ""))
    if job is not None and (not marker.get("turn_id") or job.turn_id == marker.get("turn_id")):
        await _remember_phase_session(db, run)
