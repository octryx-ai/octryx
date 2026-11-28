"""Switch a run's runtime target: an explicit run action (``change_runtime``) that prepares the new runtime."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun
from ....time_utils import utc_now
from ..records import WorkflowRunError, main_session_id, record_event
from ..states import ACTIVE_STATUSES, STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE
from .target import KIND_DEVICE, KIND_SERVER, apply_to_thread, stored_target, validate_target, with_target

ACTION_CHANGE_RUNTIME = "change_runtime"
EVENT_CHANGED = "runtime_target_changed"


async def change_runtime(db: AsyncSession, run: WorkflowRun, *, user: User, raw: Any) -> None:
    from app.services.devices.job_state import ACTIVE_STATUSES as JOB_ACTIVE

    from ...devices.jobs import thread_job
    from ..octryx.continuation_marker import CONTEXT_KEY as CONTINUATION_KEY

    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("run_not_active", "Only an active run changes where it runs.", 409)
    owner = await db.get(User, run.requested_by) if run.requested_by != user.id else user
    # A device target is always the requester's own device, also when an admin switches the run.
    raw = _keeping_model(raw, stored_target(run))
    target = await validate_target(db, user=owner or user, project_id=run.project_id, raw=raw)
    if target is None:
        raise WorkflowRunError("runtime_target_invalid", "Choose where the run executes.", 422)
    await _refuse_server_build(db, run, target, actor_id=user.id)
    from .folder_lock import refuse_busy_folder

    await refuse_busy_folder(db, target, run_id=run.id)
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    busy = await thread_job(db, thread.id) if thread is not None else None
    if busy is not None and busy.status in JOB_ACTIVE:
        raise WorkflowRunError("runtime_busy", "A device turn of this run is still running: wait for it or stop it, "
                                               "then change where the run executes.", 409)
    previous = stored_target(run)
    context = with_target(run.context, target, actor_id=user.id)
    context.pop(CONTINUATION_KEY, None)  # a pending turn for the old runtime never starts on the new one
    run.context = context
    apply_to_thread(thread, target)
    record_event(db, run, EVENT_CHANGED, node_id=run.current_node_id, actor_id=user.id,
                 detail={"from": previous, "to": target})
    if run.status == STATUS_WAITING and run.waiting_kind == WAITING_DEVICE:
        from .device_wait import leave_waiting

        leave_waiting(db, run, cause="runtime_changed")
    from .seat_required import lift_seat_pause, seat_paused

    if seat_paused(run):
        await lift_seat_pause(db, run, actor_id=user.id)
    await prepare_new_runtime(db, run)


def _keeping_model(raw: Any, previous: dict[str, Any] | None) -> Any:
    # A switch without a model must not store an empty one: the device would fall back to its own default model.
    # The pool's model is the pool's choice, never a person's device's.
    model = str((previous or {}).get("model") or "")
    if not model or (previous or {}).get("kind") != KIND_DEVICE or (previous or {}).get("pool") \
            or not isinstance(raw, dict):
        return raw
    if str(raw.get("kind") or "") != KIND_DEVICE or str(raw.get("model") or "").strip():
        return raw
    return {**raw, "model": model}


async def _refuse_server_build(db: AsyncSession, run: WorkflowRun, target: dict[str, Any], *, actor_id: str) -> None:
    from .server_build import refuse_server_build, run_definition

    definition = await run_definition(db, run)
    refuse_server_build(target, workflow_key=run.workflow_key, where="change_runtime", definition=definition,
                        actor_id=actor_id, db=db, run=run)


async def prepare_new_runtime(db: AsyncSession, run: WorkflowRun) -> None:
    from ..graph import NODE_PHASE, graph_for_run
    from ..workspace.preparation import ACTION, preparation

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if not preparation(run):
        # ``workspace.prepare`` has not run yet (or the workflow has none): it runs on the new target later. A run
        # that stands at a phase now continues that phase on the new target at once, instead of standing still.
        if node is not None and node.kind == NODE_PHASE and run.status == STATUS_RUNNING:
            await _continue_phase(db, run, node)
        return
    if node is None:
        return
    if node.config.get("action") == ACTION and run.status == STATUS_RUNNING:
        await _prepare_again(db, run, node)
        return
    await _prepare_in_place(db, run, node, at_phase=node.kind == NODE_PHASE)


async def _continue_phase(db: AsyncSession, run: WorkflowRun, node: Any) -> None:
    from ..octryx.continuation import continue_on_device
    from ..octryx.continuation_marker import CONTEXT_KEY as CONTINUATION_KEY
    from ..octryx.continuation_marker import STATE_PENDING

    target = stored_target(run) or {"kind": KIND_SERVER}
    if target["kind"] == KIND_DEVICE:
        entry = dict(run.node_state or {}).get("entry")
        run.context = {**dict(run.context or {}),
                       CONTINUATION_KEY: {"node_id": node.id, "entry": entry, "state": STATE_PENDING}}
        await continue_on_device(db, run)
    elif target["kind"] == KIND_SERVER:
        from ..server_continuation import phase_entered_on_server

        await phase_entered_on_server(db, run, node)


async def _prepare_again(db: AsyncSession, run: WorkflowRun, node: Any) -> None:
    from ..platform_actions import WAIT
    from ..workspace.preparation import _route, prepare_workspace

    outcome, route = await prepare_workspace(db, run, node)
    if route != WAIT:
        await _route(db, run, outcome)


async def _prepare_in_place(db: AsyncSession, run: WorkflowRun, node: Any, *, at_phase: bool) -> None:
    from ..octryx.continuation import continue_on_device
    from ..octryx.continuation_marker import CONTEXT_KEY as CONTINUATION_KEY
    from ..octryx.continuation_marker import STATE_PENDING
    from ..workspace.preparation import (
        STATE_NOT_READY,
        STATE_READY,
        _set,
        decide,
        requirement,
    )
    from ..workspace.preparation import STATE_PENDING as PREP_PENDING

    target = stored_target(run) or {"kind": KIND_SERVER}
    entry = dict(run.node_state or {}).get("entry")
    spec = await requirement(db, run)
    base = {"runtime": target["kind"], "node_id": node.id, "entry": entry, "spec": spec, "in_place": True,
            "at": utc_now().isoformat()}
    if target["kind"] == KIND_SERVER:
        from ..workspace.recovery import prepare_on_server, run_binding, still_bound

        binding = await run_binding(db, run, with_copy=False)
        # A recorded copy that is gone (a recreated container) is re-created first, only when that is provable.
        report = await prepare_on_server(db, run, spec) or {
            "branch": {"state": "unavailable", "detail": "the run has no server working copy"}}
        if not await still_bound(db, run, binding, with_copy=False):
            return  # the run moved, stopped or was switched meanwhile: this result is not its, nothing is written
        outcome = decide(report)
        _set(run, {**base, "state": STATE_READY if outcome.ok else STATE_NOT_READY, "report": report})
        if not outcome.ok and at_phase and run.status == STATUS_RUNNING:
            from ..workspace.readiness import pause_not_ready

            await pause_not_ready(db, run, {"kind": outcome.failure_class, "reason": outcome.reason,
                                            "source": "workspace_preparation"})
        return
    _set(run, {**base, "state": PREP_PENDING})
    if target["kind"] == KIND_DEVICE and at_phase and run.status == STATUS_RUNNING:
        run.context = {**dict(run.context or {}),
                       CONTINUATION_KEY: {"node_id": node.id, "entry": entry, "state": STATE_PENDING}}
        await continue_on_device(db, run)


__all__ = ["ACTION_CHANGE_RUNTIME", "EVENT_CHANGED", "change_runtime", "prepare_new_runtime"]
