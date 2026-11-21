"""The continuation's device turn: its session and prompt, and what a refused or started turn leaves on the run."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from ..records import record_event
from ..run_texts import run_text, run_texts
from .continuation_marker import BUSY_SINCE_KEY, FRESH_KEY, PROVENANCE, STATE_REFUSED, STATE_STARTED, _set_marker
from .continuation_prompts import _epic_prompt, _prompt, plain_story_prompt
from .phase_sessions import RESUME_EPIC, _resumable_session
from .turn_failures import ATTEMPT_RETRY
from .turn_offered import _offered_after_commit


async def _start_continuation_turn(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any], node: PhasedNode,
                                   turn_node: PhasedNode, thread: Session, target: dict[str, Any], suffix: str) -> Any:
    """Start the continuation's device turn on ``target``: the resumed or fresh session and the platform's prompt."""
    from ...devices.chat_turn import start_device_turn

    # A fresh session per pass costs 3-19 min of re-orientation each; plain
    # Claude Code builds a story in one session. A pass of the same phase resumes that phase's session.
    # "Continue in a new chat" starts the pass over in a fresh session (:func:`continue_in_new_thread`).
    resume, why = ("", "") if marker.get(FRESH_KEY) else await _resumable_session(db, run, turn_node, target)
    from .compaction import compacts_itself
    from .context_cap import over_cap, source_run_id

    # A Claude Code session compacts itself at the class's window (``compaction``); only another engine restarts.
    capped = bool(resume) and not await compacts_itself(db, resume) and await over_cap(
        db, run, source_run_id=source_run_id(run, epic=why == RESUME_EPIC), node_id=turn_node.id)
    if capped:  # past the class's context cap: a fresh session, the branch carries the work
        resume, why = "", ""
    prompt = await _continuation_prompt(db, run, marker, node, turn_node, resume=resume, why=why, capped=capped)
    # The launcher may run the pipeline or the hands-on test first and end the job without an agent when they are
    # green; the prompt reaches the chat only when the turn really starts (``deferred_turn_message``).
    return await start_device_turn(db, user_id=thread.user_id, prompt=prompt, target=target,
                                   session_id=thread.id, fresh_session=not resume, resume_session_id=resume,
                                   idempotency_key=f"{PROVENANCE}:{run.id}:{marker.get('entry')}{suffix}"[:100],
                                   message_on_accept=True)


async def _continuation_prompt(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any], node: PhasedNode,
                               turn_node: PhasedNode, *, resume: str, why: str, capped: bool) -> str:
    """The continuation turn's prompt in the run's texts (its workflow's and Workspace's catalog versions)."""
    from .run_session import RESUME_RUN, next_phase_prompt

    async with run_texts(db, run):
        prompt = (_epic_prompt(run, turn_node) if why == RESUME_EPIC
                  else next_phase_prompt(run, turn_node) if why == RESUME_RUN
                  else _prompt(run, node, resumed=bool(resume), retry=marker.get("attempt") == ATTEMPT_RETRY,
                               then=turn_node if turn_node is not node else None))
        if why == RESUME_EPIC or not resume:
            prompt = await plain_story_prompt(db, run, turn_node, epic=why == RESUME_EPIC) or prompt
        if capped:
            prompt = f"{run_text('context_cap.handoff')}\n\n{prompt}"
    return prompt


def _turn_refused(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any], node: PhasedNode, started: Any,
                  target: dict[str, Any]) -> None:
    """The device refused the continuation turn: the run waits for the device, or with a card saying why."""
    from ..runtime_target.device_wait import WAITABLE_REASONS, wait_for_device
    from .seat_fallback import REASON_NO_SAME_CLASS

    if started.reason == REASON_NO_SAME_CLASS:  # the run paused with the seat model and the reset
        _set_marker(run, None)
        return

    if started.reason in WAITABLE_REASONS:  # offline, paused, busy: the run waits; the same turn starts later
        wait_for_device(db, run, node_id=node.id, reason=started.reason, thread_target=target)
        return
    _set_marker(run, {**marker, "state": STATE_REFUSED, "reason": started.reason})
    record_event(db, run, "device_continuation_refused", node_id=node.id, detail={"reason": started.reason})
    # Never a silent "running" run that nothing continues: it waits with a card that says why and what to do.
    from ..runtime_target.device_wait import wait_refused

    wait_refused(db, run, node_id=node.id, reason=started.reason, thread_target=target)


async def _turn_started(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any], node: PhasedNode,
                        started: Any) -> str:
    """The continuation turn started: the marker names its job and an open chat shows the offered turn."""
    from ....models import DeviceJob
    from ....time_utils import utc_now

    job = await db.get(DeviceJob, started.job_id)
    if marker.get(BUSY_SINCE_KEY):  # measured from the first refusal; a later refusal of this turn waits on from there
        from ...devices import busy_wait

        busy_wait.observe("phase", "ran", busy_wait.waited_seconds(marker[BUSY_SINCE_KEY]))
    _set_marker(run, {**marker, "state": STATE_STARTED, "job_id": started.job_id, "started_at": utc_now().isoformat(),
                      "phase": node.kind == NODE_PHASE, "turn_id": job.turn_id if job is not None else None})
    record_event(db, run, "device_continuation_started", node_id=node.id, detail={"job_id": started.job_id})
    await _offered_after_commit(db, started.job_id)
    return started.job_id
