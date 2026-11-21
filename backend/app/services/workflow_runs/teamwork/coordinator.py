"""The board wakes the coordinator while its items run.

An item agent that needs the coordinator never waits: it posts a ``question`` to the coordinator's agent hash and
finishes ``blocked``. While the run is at its ``parallel_work`` node nobody else drives the coordinator, and its
Claude Code session has ended (one device job is one turn), so a post addressed to ``context.work.coordinator_hash``
starts one coordinator turn on the run's main device thread:

- the turn resumes the coordinator's own session (the plan phase's remembered session, same device, folder and
  profile) on the plan phase's model, with a prompt that names the new message ids; the coordinator answers with
  ``board_post reply_to`` and may submit a revised plan;
- **once per message**: a message already woken for, or already waiting, starts nothing; messages that arrive while
  a wake waits ride along with it;
- **deferred while the main thread is busy** (the turn that submitted the plan, a work-git step, the previous wake):
  the wake waits in ``context.coordinator_wake.pending`` and starts when that job ends (:func:`main_turn_ended`,
  called from the device job end);
- **nothing when the run is not at ``parallel_work``**: before the split exists, after it resolved (the coordinator
  gets the findings and the story's board thread at ``replan``), or on a paused run.

The coordinator's hash is the board agent hash of the gateway session that submitted the plan
(``context.work.coordinator_session_id``, :func:`coordinator_hash`); it stays the address for the whole split, even
though each woken turn runs in a gateway session of its own. Only device runs have one: server agents have no board
tools yet and go through ``replan``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..records import record_event
from ..states import STATUS_RUNNING
from . import WORK_KEY, work_of

logger = logging.getLogger(__name__)

WAKE_KEY = "coordinator_wake"  # {"pending": [message ids], "woken": [message ids], "job_id", "at"}
EVENT_WOKEN = "coordinator_woken"
EVENT_WAKE_REFUSED = "coordinator_wake_refused"
PROVENANCE = "teamwork_coordinator_wake"


def at_parallel_work(run: WorkflowRun) -> bool:
    """The run stands at its ``parallel_work`` node with the split still open (the only time a wake starts)."""
    work = work_of(run)
    return (run.status == STATUS_RUNNING and bool(work.get("node_id"))
            and run.current_node_id == work.get("node_id") and not work.get("route"))


async def coordinator_hash(db: AsyncSession, run: WorkflowRun) -> str | None:
    """The board agent hash of the session that submitted the plan (stored, else derived from its session key)."""
    work = work_of(run)
    if work.get("coordinator_hash"):
        return str(work["coordinator_hash"])
    session_id = work.get("coordinator_session_id")
    session = await db.get(Session, str(session_id)) if session_id else None
    from ...agent_gateway.presence import session_key_hash
    from ...agent_gateway.sessions import SESSION_KEY_METADATA

    key = str(dict(session.metadata_ or {}).get(SESSION_KEY_METADATA) or "") if session is not None else ""
    return session_key_hash(key) if key else None


async def fill_coordinator_hash(db: AsyncSession, run: WorkflowRun) -> str | None:
    """Store :func:`coordinator_hash` on ``context.work`` (the run view and the team block show it)."""
    value = await coordinator_hash(db, run)
    work = work_of(run)
    if value and work and work.get("coordinator_hash") != value:
        run.context = {**dict(run.context or {}), WORK_KEY: {**work, "coordinator_hash": value}}
    return value


async def _run_of_coordinator(db: AsyncSession, project_id: str, agent_hash: str) -> WorkflowRun | None:
    """The Workspace's running run at ``parallel_work`` whose coordinator has ``agent_hash``."""
    runs = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == project_id, WorkflowRun.status == STATUS_RUNNING))).scalars().all()
    for run in runs:
        if at_parallel_work(run) and await coordinator_hash(db, run) == agent_hash:
            return run
    return None


def _wake(run: WorkflowRun) -> dict[str, Any]:
    value = dict(run.context or {}).get(WAKE_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _set_wake(run: WorkflowRun, wake: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), WAKE_KEY: wake}


async def board_posted(db: AsyncSession, message: Any) -> str | None:
    """A board post was stored: when it is addressed to a running split's coordinator, wake it (the job id, or
    ``None`` when nothing started now). Never fails the post."""
    if not message.to_agent_hash or message.author_agent_hash == message.to_agent_hash:
        return None
    try:
        run = await _run_of_coordinator(db, message.project_id, message.to_agent_hash)
        if run is None:
            return None
        from ..records import lock_run

        run = await lock_run(db, run)
        wake = _wake(run)
        if message.id in (wake.get("pending") or []) or message.id in (wake.get("woken") or []):
            return None
        _set_wake(run, {**wake, "pending": [*(wake.get("pending") or []), message.id]})
        await fill_coordinator_hash(db, run)
        return await start_pending_wake(db, run)
    except Exception:  # noqa: BLE001 - the message stands; the coordinator reads it at the next replan
        logger.exception("teamwork: coordinator wake for board message %s failed", getattr(message, "id", "?"))
        return None


def _prompt(run: WorkflowRun, message_ids: list[str]) -> str:
    work = work_of(run)
    open_items = [key for key, item in dict(work.get("items") or {}).items()
                  if dict(item).get("status") not in ("merged",)]
    from ..run_texts import run_text

    return run_text("coordinator.board", run_id=run.id, messages=", ".join(message_ids),
                    open_items=", ".join(open_items) or "none")


async def _coordinator_session(db: AsyncSession, run: WorkflowRun, target: dict[str, Any]) -> str:
    """The Claude Code session the coordinator's plan pass ran in, on this device, folder and profile."""
    from ..octryx.phase_sessions import _node_session, _pass_session, _session_here

    plan_node = str(work_of(run).get("plan_node") or "")
    entry = _node_session(run, plan_node)
    if not entry:
        last = await _pass_session(db, run)
        entry = last if last is not None and last.get("node_id") == plan_node else {}
    return await _session_here(db, entry, target)


async def start_pending_wake(db: AsyncSession, run: WorkflowRun) -> str | None:
    """Start the waiting wake on the run's main device thread when it is free; the job id, else ``None``.

    The caller holds the run claim. A run that left ``parallel_work`` drops what waits: the coordinator reads the
    board thread at its replan pass instead."""
    wake = _wake(run)
    pending = [str(value) for value in wake.get("pending") or []]
    if not pending:
        return None
    if not at_parallel_work(run):
        _set_wake(run, {**wake, "pending": []})
        return None
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.chat_turn import DeviceTurnStarted, start_device_turn
    from ...devices.jobs import thread_job
    from ..graph import graph_for_run
    from ..octryx.continuation_marker import _device_target
    from ..octryx.turn_settings import _with_run_settings
    from ..records import main_session_id

    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    target = _device_target(thread)
    if target is None:
        _set_wake(run, {**wake, "pending": []})  # not a device run: no board, nothing to wake
        return None
    busy = await thread_job(db, thread.id)
    if busy is not None and busy.status in ACTIVE_STATUSES:
        return None  # deferred: starts when that job ends (main_turn_ended)
    plan = (await graph_for_run(db, run)).nodes.get(str(work_of(run).get("plan_node") or ""))
    if plan is not None:
        target = await _with_run_settings(db, run, plan, target)
    resume = await _coordinator_session(db, run, target)
    from ..run_texts import run_texts

    async with run_texts(db, run):
        prompt = _prompt(run, pending)
    started = await start_device_turn(
        db, user_id=thread.user_id, prompt=prompt, target=target, session_id=thread.id,
        fresh_session=not resume, resume_session_id=resume,
        idempotency_key=f"{PROVENANCE}:{run.id}:{pending[-1]}"[:100])
    node_id = run.current_node_id
    if not isinstance(started, DeviceTurnStarted):
        # Offline, paused or refused: the messages wait; the next post or job end tries again.
        record_event(db, run, EVENT_WAKE_REFUSED, node_id=node_id, detail={"reason": started.reason,
                                                                             "message_ids": pending})
        return None
    from ....time_utils import utc_now

    _set_wake(run, {"pending": [], "woken": [*(wake.get("woken") or []), *pending], "job_id": started.job_id,
                    "at": utc_now().isoformat()})
    record_event(db, run, EVENT_WOKEN, node_id=node_id, detail={"job_id": started.job_id, "message_ids": pending,
                                                                "resumed": bool(resume)})
    return started.job_id


async def main_turn_ended(db: AsyncSession, session_id: str) -> str | None:
    """A device job of a thread ended: a wake that waited for the run's main thread starts now."""
    from ..records import active_run_for_session, lock_run

    run = await active_run_for_session(db, session_id)
    if run is None or not _wake(run).get("pending"):
        return None
    return await start_pending_wake(db, await lock_run(db, run))


__all__ = ["EVENT_WOKEN", "WAKE_KEY", "at_parallel_work", "board_posted", "coordinator_hash",
           "fill_coordinator_hash", "main_turn_ended", "start_pending_wake"]
