"""The next phase of a Server run starts by itself."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, WorkflowRun
from .states import STATUS_RUNNING

logger = logging.getLogger(__name__)

CONTEXT_KEY = "server_continuation"
STATE_PENDING = "pending"
STATE_STARTED = "started"
EVENT_STARTED = "server_continuation_started"
EVENT_REFUSED = "server_continuation_refused"
EVENT_MODEL_REFUSED = "run_turn_model_refused"
CODE_TURN_FAILED = "server_turn_failed"
_AFTER_COMMIT_KEY = "workflow_server_continuation"


def _marker(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def _set_marker(run: WorkflowRun, marker: dict[str, Any] | None) -> None:
    context = dict(run.context or {})
    if marker is None:
        context.pop(CONTEXT_KEY, None)
    else:
        context[CONTEXT_KEY] = marker
    run.context = context


def _current_pass(run: WorkflowRun, marker: dict[str, Any]) -> bool:
    return (run.status == STATUS_RUNNING and bool(marker)
            and (marker.get("node_id"), marker.get("entry")) == (run.current_node_id,
                                                                 dict(run.node_state or {}).get("entry")))


async def _drives_itself(db: AsyncSession, run: WorkflowRun, thread: Session | None) -> bool:
    from .automation import is_action_started
    from .runtime_target.target import KIND_SERVER, stored_target

    target = stored_target(run)
    if thread is None or not target or target.get("kind") != KIND_SERVER:
        return False
    if dict(run.context or {}).get("fixture"):
        return False  # an acceptance fixture (``attention.fixtures``) never costs a model turn
    if isinstance(dict(thread.metadata_ or {}).get("execution_target"), dict):
        return False
    return not await is_action_started(db, run)


async def phase_entered_on_server(db: AsyncSession, run: WorkflowRun, node: Any) -> None:
    from .records import main_session_id

    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    if not await _drives_itself(db, run, thread):
        return
    _set_marker(run, {"node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "state": STATE_PENDING})
    _after_commit(db, thread.id)


def _after_commit(db: AsyncSession, session_id: str) -> None:
    sync = db.sync_session
    sync.info.setdefault(_AFTER_COMMIT_KEY, set()).add(session_id)
    if not event.contains(sync, "after_commit", _schedule_pending):
        event.listen(sync, "after_commit", _schedule_pending)
        event.listen(sync, "after_rollback", _drop_pending)


def _schedule_pending(sync_session: Any) -> None:
    for session_id in sync_session.info.pop(_AFTER_COMMIT_KEY, set()):
        schedule_continuation(session_id)


def _drop_pending(sync_session: Any) -> None:
    sync_session.info.pop(_AFTER_COMMIT_KEY, None)


def schedule_continuation(session_id: str, *, session_factory=None) -> None:
    import asyncio

    from ..chat_turn_background import schedule_chat_turn_background_task

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    schedule_chat_turn_background_task(
        session_id=session_id, task_name="workflow_server_continuation",
        coro_factory=lambda: start_pending_turn(session_id, session_factory=session_factory))


async def phase_runtime_target_id(db: AsyncSession, model: str) -> str | None:
    from ..control_plane_service import get_runtime_targets

    wanted = str(model or "").strip()
    if not wanted:
        return None
    targets = await get_runtime_targets(db, active_only=True)
    for matches in (lambda name: name == wanted, lambda name: name.endswith(f".{wanted}")):
        found = next((target for target in targets if matches(str(target.model_id or ""))), None)
        if found is not None:
            return str(found.id)
    return None


async def _claim(db: AsyncSession, session_id: str) -> tuple[WorkflowRun, Session, str, str | None] | None:
    from .graph import graph_for_run
    from .octryx.continuation_prompts import _prompt
    from .octryx.turn_settings import turn_phase_model
    from .records import active_run_for_session, lock_run

    thread = await db.get(Session, session_id)
    run = await active_run_for_session(db, session_id)
    if thread is None or run is None or _marker(run).get("state") != STATE_PENDING:
        return None
    if thread.status == "running":
        return None
    run = await lock_run(db, run)
    marker = _marker(run)
    if marker.get("state") != STATE_PENDING:
        return None
    if not _current_pass(run, marker):
        _set_marker(run, None)
        return None
    node = (await graph_for_run(db, run)).nodes[str(marker["node_id"])]
    _set_marker(run, {**marker, "state": STATE_STARTED})
    return run, thread, _prompt(run, node), await phase_runtime_target_id(db, turn_phase_model(run, node))


async def start_pending_turn(session_id: str, *, session_factory=None) -> None:
    from ...db import core as db_core
    from ..session.message_dispatch import send_session_message
    from ..session.turn_refusals import TurnRefusal
    from .records import WorkflowRunError, record_event

    factory = session_factory or db_core.async_session_factory
    async with factory() as db:
        try:
            claimed = await _claim(db, session_id)
        except WorkflowRunError:
            return  # the run is changing right now: whoever changes it decides how it goes on
        if claimed is None:
            await db.commit()
            return
        run, thread, prompt, runtime_target_id = claimed
        record_event(db, run, EVENT_STARTED, node_id=run.current_node_id,
                     detail={"session_id": thread.id, "runtime_target_id": runtime_target_id})
        run_id, user_id, project_id = run.id, thread.user_id, thread.project_id
        await db.commit()

        async def send(target_id: str | None):
            return await send_session_message(db, session_id=session_id, content=prompt, user_id=user_id,
                                              project_id=project_id, runtime_target_id=target_id,
                                              session_factory=factory)

        try:
            outcome = await send(runtime_target_id)
            if runtime_target_id and isinstance(outcome, TurnRefusal) and str(outcome.state) in _MODEL_REFUSALS:
                # The phase's model may not answer in this Workspace: the thread's runtime instead, visibly.
                await _model_refused(db, run_id, runtime_target_id, str(outcome.state))
                outcome = await send(None)
        except Exception:  # noqa: BLE001 - the turn runner settled the turn; the run must not stay silent
            logger.warning("workflow_run.server_continuation_failed run_id=%s", run_id, exc_info=True)
            return
        if isinstance(outcome, TurnRefusal):
            await _refused(db, run_id, str(outcome.state))


_MODEL_REFUSALS = frozenset({"runtime_not_allowed", "runtime_requirement_unmet", "runtime_target_invalid"})


async def _model_refused(db: AsyncSession, run_id: str, runtime_target_id: str, reason: str) -> None:
    from .records import record_event

    run = await db.get(WorkflowRun, run_id)
    if run is not None:
        record_event(db, run, EVENT_MODEL_REFUSED, node_id=run.current_node_id,
                     detail={"runtime_target_id": runtime_target_id, "reason": reason})
        await db.commit()


async def _refused(db: AsyncSession, run_id: str, reason: str) -> None:
    from .limits import pause_run
    from .records import lock_run_id, record_event
    from .states import PAUSE_RUNTIME_FAILED

    run = await lock_run_id(db, run_id)
    if run is None or not _current_pass(run, _marker(run)):
        return
    record_event(db, run, EVENT_REFUSED, node_id=run.current_node_id, detail={"reason": reason})
    _set_marker(run, None)
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": f"The platform could not start this phase's turn ({reason}). Continue to try again, or abort.",
        "code": f"server_turn_refused_{reason}"[:80], "resume": {"kind": "restart", "node_id": run.current_node_id},
    })
    await db.commit()


async def server_turn_ended(session_id: str, *, failed: bool, session_factory=None) -> None:
    from ...db import core as db_core
    from .limits import pause_run
    from .records import WorkflowRunError, active_run_for_session, lock_run
    from .states import PAUSE_RUNTIME_FAILED

    factory = session_factory or db_core.async_session_factory
    async with factory() as db:
        run = await active_run_for_session(db, session_id)
        marker = _marker(run) if run is not None else {}
        if run is None or not marker:
            return
        if failed and marker.get("state") == STATE_STARTED and _current_pass(run, marker):
            try:
                run = await lock_run(db, run)
            except WorkflowRunError:
                return
            if _current_pass(run, _marker(run)) and _marker(run).get("state") == STATE_STARTED:
                _set_marker(run, None)
                await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
                    "message": ("The platform's turn for this phase failed before finishing it "
                                f"({CODE_TURN_FAILED}). Continue to run the phase again, or abort the run."),
                    "code": CODE_TURN_FAILED, "resume": {"kind": "restart", "node_id": run.current_node_id},
                })
                await db.commit()
            return
    if marker.get("state") == STATE_PENDING:
        schedule_continuation(session_id, session_factory=session_factory)


__all__ = ["CONTEXT_KEY", "EVENT_STARTED", "phase_entered_on_server", "phase_runtime_target_id",
           "schedule_continuation", "server_turn_ended", "start_pending_turn"]
