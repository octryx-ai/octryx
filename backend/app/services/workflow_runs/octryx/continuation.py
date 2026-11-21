"""The next phase continues on the device by itself.

When a run enters a phase — a watched state was met, a person decided (in the platform or the terminal), a gate
looped back — the phase must not wait for someone to type a prompt:

- an **interactive terminal** session gets the new contract at its next hook answer (every gateway answer of a bound
  session carries it; the prompt hook asks for it too);
- a run whose chat thread runs **on a device** (``execution_target.kind == "device"``) gets a new device job turn on
  that thread, through the same dispatch as a chat message (``devices.chat_turn.start_device_turn``: owner, device
  online, folder, profile, Workspace policy). One turn per pass (``node_id`` + ``entry``): while the thread's job is
  still busy (the turn whose Stop advanced the run) the continuation stays pending and starts when that turn finishes
  (``devices.jobs`` → :func:`continue_on_device`).

A device that cannot take the turn now (offline, paused, at its job limit) holds the run ``waiting_for_device``
with the continuation still pending; it starts when the device can (``runtime_target.device_wait``).

Only a running run at a phase (or at ``workspace.prepare``, whose turn the launcher prepares before the agent starts)
continues: a paused or waiting run, a gate or an outcome never starts a turn, and a pending continuation of an older
pass is dropped — so a turn whose tests could not run (the run paused ``environment_not_ready``) is never followed by
another one by itself. The turn's prompt only names the phase; what the turn may do is the
phase's class, tools and path rules, decided again at every hook.

A new phase starts a fresh Claude Code session; another pass of the **same** phase (an automatic revision, a product
owner's answer, a red pipeline) resumes that phase's own session with a short prompt naming what changed
(:data:`SESSIONS_KEY`, one session per phase node, so a loop back over several phases resumes each one's own). A phase
with ``config.session: "epic"`` also resumes its session of the epic's previous story (``context.epic_chain``) on
the same device, folder and profile, with a short "new story of the same epic" prompt. A phase's explicit
``config.model`` is the turn's model on every profile (seat and governed); a model the Workspace
refuses falls back to the device default with the event ``run_turn_model_refused``. A phase turn that failed on a
temporary model service error runs once more by itself after a short wait (:func:`is_transient_failure`) instead
of pausing the run; so is a phase turn the launcher refused before the agent started because it could not reach the
platform (:func:`is_transient_rejection`). Any other refusal, or the second one, pauses the run ``runtime_failed``.

The turn of a runtime step (``workspace.prepare``) whose success leads into a phase is that phase's turn: the launcher
prepares the folder and the agent goes on with the phase (team-delivery: prepare → plan), so it runs on the phase's
model and resumes the phase's session, and once the run enters the phase the turn counts as the phase's pass (its
session is remembered under the phase when the turn ends).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from ..records import main_session_id, record_event
from ..states import STATUS_RUNNING
from .continuation_marker import (
    STATE_PENDING,
    STATE_STARTED,
    THEN_KEY,
    _current_pass_started,
    _device_target,
    _marker,
    _set_marker,
)
from .continuation_turn import _start_continuation_turn, _turn_refused, _turn_started
from .phase_sessions import _remember_ended_pass, _remember_phase_session
from .run_turn import REASON_SEAT_LIMIT, _switch_to_governed, start_run_turn
from .turn_failures import (
    CODE_SEAT_LIMIT,
    _pause_failed_phase_turn,
    _pause_unfinished_phase_turn,
    _retry_after_transient_failure,
    _wait_while_device_busy,
    failed_turn_explanation,
)


async def phase_entered(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> None:
    """The run entered ``node``: a device thread continues it (now, or when its busy turn finishes)."""
    if node.kind != NODE_PHASE:
        return
    thread_id = await main_session_id(db, run)
    if _device_target(await db.get(Session, thread_id) if thread_id else None) is None:
        # A Server run starts the phase's turn itself; an interactive terminal gets the contract at its next hook.
        from ..server_continuation import phase_entered_on_server

        await phase_entered_on_server(db, run, node)
        return
    from ...devices.jobs import thread_job

    if _carried_into(run, node, _marker(run), await thread_job(db, thread_id)):
        return
    await _remember_phase_session(db, run)
    _set_marker(run, {"node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "state": STATE_PENDING})
    await continue_on_device(db, run)


async def runtime_step_entered(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> None:
    """A runtime step (``workspace.prepare``) waits for the device's launcher: a device thread gets the turn whose
    preparation reports it; a terminal prepares at its next launch.

    The agent of that turn goes on with the phase the step leads to (its contract follows the run), so the turn is
    that phase's: its model and its resumable session (:data:`THEN_KEY`)."""
    thread_id = await main_session_id(db, run)
    if _device_target(await db.get(Session, thread_id) if thread_id else None) is None:
        return
    await _remember_phase_session(db, run)
    following = await _following_phase(db, run, node)
    _set_marker(run, {"node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "state": STATE_PENDING,
                      **({THEN_KEY: following} if following else {})})
    await continue_on_device(db, run)


async def _following_phase(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> str:
    """The phase the agent of a platform-action step's turn goes on with: the phase the step enters when it succeeds
    (``workspace.prepare`` → team-delivery's ``plan``); for the CI pipeline, whose success leads to the server's
    review, the phase a red pipeline returns to (``implement``). ``""`` when neither is a phase.

    Otherwise every red pipeline's fix ran in the pipeline turn's own
    FRESH session (4 new sessions in one story, each re-reading the contract and the specification), although the
    building phase's session held all of it. As the pipeline turn's phase, a red pipeline resumes that session; a
    green one ends the turn before any agent starts (the launcher's ``pipeline_done``)."""
    from ..graph import FAILED, NODE_PLATFORM_ACTION, SUCCEEDED, graph_for_run
    from ..pipeline import ACTION as PIPELINE_ACTION

    if node.kind != NODE_PLATFORM_ACTION:
        return ""
    graph = await graph_for_run(db, run)
    from ..hands_on.step import ACTION as HANDS_ON_ACTION

    looped = node.config.get("action") in (PIPELINE_ACTION, HANDS_ON_ACTION)  # red goes back to the building phase
    routes = (SUCCEEDED, FAILED) if looped else (SUCCEEDED,)
    for route in routes:
        edge = next((edge for edge in graph.exits(node.id) if edge.when == route), None)
        target = graph.nodes.get(edge.target) if edge is not None else None
        if target is not None and target.kind == NODE_PHASE:
            from ..size_class.merge import merges

            return merges(run).get(target.id, target.id)  # a phase its class does inside a later one: that one
    return ""


def _carried_into(run: WorkflowRun, node: PhasedNode, marker: dict[str, Any], busy: Any) -> bool:
    """The run entered ``node`` while the runtime step's turn that leads to it still runs: that turn's agent does
    this phase (e.g. the coordinator's plan runs inside the
    prepare turn). The marker becomes this phase's started pass, so its session is remembered under the phase and the
    turn's end is judged as the phase's."""
    from app.services.devices.job_state import ACTIVE_STATUSES

    if marker.get(THEN_KEY) != node.id or marker.get("state") != STATE_STARTED or busy is None:
        return False
    if busy.status not in ACTIVE_STATUSES or busy.id != marker.get("job_id"):
        return False
    _set_marker(run, {**{key: value for key, value in marker.items() if key != THEN_KEY}, "node_id": node.id,
                      "entry": dict(run.node_state or {}).get("entry"), "phase": True})
    return True


async def continue_on_device(db: AsyncSession, run: WorkflowRun) -> str | None:
    """Start the pending continuation's device turn when the run still is at that pass; the job id or ``None``."""
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.chat_turn import DeviceTurnStarted
    from ...devices.jobs import thread_job
    from ..graph import graph_for_run
    from ..handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    marker = _marker(run)
    if marker.get("state") != STATE_PENDING:
        return None
    current = (run.current_node_id, dict(run.node_state or {}).get("entry"))
    if run.status != STATUS_RUNNING or current != (marker.get("node_id"), marker.get("entry")):
        _set_marker(run, None)  # paused, waiting, or already another pass: nothing continues this one
        return None
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    target = _device_target(thread)
    busy = await thread_job(db, thread.id) if thread is not None else None
    if target is None or (busy is not None and busy.status in ACTIVE_STATUSES):
        return None  # still the turn that advanced the run: it starts when that turn finishes
    graph = await graph_for_run(db, run)
    node = graph.nodes[str(marker["node_id"])]
    # A runtime step's turn goes on with the phase after it: that phase's model and session.
    turn_node = graph.nodes.get(str(marker.get(THEN_KEY) or "")) or node
    # The turn's prompt is the platform's, not the user's: its message carries that provenance.
    attempt = f":{marker['attempt']}" if marker.get("attempt") else ""

    async def start(target: dict[str, Any], suffix: str) -> Any:
        return await _start_continuation_turn(db, run, marker, node, turn_node, thread, target, suffix)

    from ..runtime_target.device_wait import REASON_FOLDER_BUSY, wait_for_device
    from ..runtime_target.folder_lock import folder_holder
    from ..runtime_target.target import stored_target

    # The run may have left its folder while it watched its pull request; another run may hold it now.
    if await folder_holder(db, stored_target(run) or {**dict(target), "kind": "device"}, run_id=run.id) is not None:
        wait_for_device(db, run, node_id=node.id, reason=REASON_FOLDER_BUSY, thread_target=target)
        return None
    started, target = await start_run_turn(db, run, turn_node, thread, target, start, suffix=attempt)
    if not isinstance(started, DeviceTurnStarted):
        _turn_refused(db, run, marker, node, started, target)
        return None
    return await _turn_started(db, run, marker, node, started)


async def continue_after_device_turn(db: AsyncSession, session_id: str, *, failure: str | None = None,
                                     said: str = "", rejected: bool = False, seat_rate_limits: Any = None) -> None:
    """A device turn of a run's thread finished: start the continuation it left pending.

    ``failure`` is the device's reason when the turn did not succeed (an API error, ``turn_stalled``, the job
    limit, a lost device). When that turn was the platform's own continuation of the current phase, nothing would
    drive the run again: it pauses ``runtime_failed`` instead of staying ``running`` (Continue runs the phase
    again, Abort ends it). ``rejected``: the device refused the turn before its agent started (``job_rejected``).
    """
    from ..records import active_run_for_session, lock_run

    run = await active_run_for_session(db, session_id)
    if run is None:
        return
    from ..teamwork.device_items import job_ended

    if await job_ended(db, run, session_id, failure=failure, said=said):
        return  # an item's turn or teamwork's git work: the scheduler took it
    marker = _marker(run)
    if marker:
        # Claim the run before judging its pass. Example: the launcher's
        # workspace-preparation report moved the run from ``prepare`` into ``implement`` but answered after the
        # launcher's timeout, so the launcher refused the turn (``workspace_preparation_platform_unreachable``) while
        # that report still held the run. The marker read here was the ``prepare`` pass; the claim below waited and
        # re-read the run at ``implement``, so no branch matched and the run stayed ``running`` with nothing driving it.
        run = await lock_run(db, run)
        marker = _marker(run)
    if marker.get("state") == STATE_STARTED and marker.get("phase"):
        run = await lock_run(db, run)
        await _remember_ended_pass(db, run, marker)
    from ..refusals import apply_pending_change_plan

    if await apply_pending_change_plan(db, await lock_run(db, run)):
        return  # a phase's refusals rule sends the run back to its node now that the refused turn ended
    if marker.get("state") == STATE_PENDING:
        await continue_on_device(db, await lock_run(db, run))
    elif failure and _current_pass_started(run, marker) and await _continue_governed_after_seat_limit(
            db, await lock_run(db, run), marker, said, failure=failure, seat_rate_limits=seat_rate_limits):
        return
    elif failure and rejected and _current_pass_started(run, marker) and await _wait_while_device_busy(
            db, await lock_run(db, run), failure):
        return
    elif failure and _current_pass_started(run, marker) and await _retry_after_transient_failure(
            db, await lock_run(db, run), failure, said, rejected=rejected):
        return
    elif failure and _current_pass_started(run, marker):
        await _pause_failed_phase_turn(db, await lock_run(db, run), failure, said, rejected=rejected)
    elif _current_pass_started(run, marker):
        # The platform's turn ended without finishing the phase (its checks never passed): the run would stay
        # "running" with nobody driving it. Pause it with the agent's
        # own words as the reason.
        await _pause_unfinished_phase_turn(db, await lock_run(db, run), said)


async def _continue_governed_after_seat_limit(db: AsyncSession, run: WorkflowRun, marker: dict[str, Any],
                                              said: str, *, failure: str = "error",
                                              seat_rate_limits: Any = None) -> bool:
    """A seat turn that hit the account's usage limit runs again at once on the governed profile (the
    subscription cannot bill any more), on a company model of the seat model's
    class until the reset (``octryx.seat_fallback``). ``False`` when this does not apply."""
    from ....time_utils import utc_now
    from ...devices.seat_quota import turn_limit
    from ..review.choice import run_engine
    from ..runtime_target.target import stored_target

    if failed_turn_explanation(failure, said)[0] != CODE_SEAT_LIMIT or marker.get("attempt") == "seat-limit":
        return False
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    target = stored_target(run) or dict(_device_target(thread) or {})
    if thread is None or target.get("profile") != "seat":
        return False
    words = " ".join(str(said or "").split())[:200]
    # Codex's record of the exhausted window (``seat_rate_limits``, read from the rollout): the exact reset.
    # the turn said "try again at 10:44 AM" and the rollout said 09:44:48 UTC, yet the pause
    # read "reset not named" because only the text reached this check.
    limit = turn_limit({"status": "error", "result_text": said, "error": failure,
                        "seat_rate_limits": seat_rate_limits}, said_at=utc_now())
    await _switch_to_governed(db, run, thread, node_id=str(run.current_node_id), reason=REASON_SEAT_LIMIT,
                              limit=limit, engine=await run_engine(db, run))
    record_event(db, run, "seat_usage_limit", node_id=run.current_node_id, detail={"said": words})
    _set_marker(run, {**marker, "state": STATE_PENDING, "attempt": "seat-limit"})
    return await continue_on_device(db, run) is not None


__all__ = ["continue_after_device_turn", "continue_on_device", "phase_entered", "runtime_step_entered"]

# Teamwork's device executor registers itself with the scheduler (``teamwork.register_executor``); continuation is
# loaded with every device run, so a run whose thread runs on a device finds it at its ``parallel_work`` node.
from ..teamwork import device_items as _device_items  # noqa: E402,F401 - side effect: registers the device executor
