""""Continue in a new chat" (``resume_in_new_session``) of a run that executes on a device."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun
from ..graph import NODE_PHASE, graph_for_run
from ..records import lock_run, main_session_id
from ..run_sessions import new_bound_session
from ..states import STATUS_RUNNING, STATUS_WAITING, WAITING_DEVICE


async def continue_in_new_thread(db: AsyncSession, run: WorkflowRun, user: User) -> Session:
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.jobs import thread_job
    from ..runtime_target.device_wait import leave_waiting
    from ..runtime_target.target import KIND_DEVICE, apply_to_thread, stored_target
    from .continuation import _following_phase, continue_on_device
    from .continuation_marker import FRESH_KEY, STATE_PENDING, THEN_KEY, _device_target, _marker, _set_marker

    run = await lock_run(db, run)
    previous_id = await main_session_id(db, run)
    previous = await db.get(Session, previous_id) if previous_id else None
    thread = await new_bound_session(db, run, user)
    if await main_session_id(db, run) != thread.id:
        return thread  # bound to the run's active sub-workflow instead: that run decides its own turns
    target = stored_target(run) or _device_target(previous)
    if target is None or target.get("kind") != KIND_DEVICE:
        return thread
    apply_to_thread(thread, target)
    busy = await thread_job(db, previous.id) if previous is not None else None
    if busy is not None and busy.status in ACTIVE_STATUSES:
        return thread
    waiting = run.status == STATUS_WAITING and run.waiting_kind == WAITING_DEVICE
    if run.status != STATUS_RUNNING and not waiting:
        return thread
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    entry = dict(run.node_state or {}).get("entry")
    marker = _marker(run)
    this_pass = (marker.get("node_id"), marker.get("entry")) == (run.current_node_id, entry)
    if node is None or (node.kind != NODE_PHASE and not this_pass):
        return thread  # a step without a device turn of its own (a review, a gate)
    if waiting:
        leave_waiting(db, run, cause="new_chat")
    following = marker.get(THEN_KEY) if this_pass else ""
    if not following and node.kind != NODE_PHASE:
        following = await _following_phase(db, run, node)
    _set_marker(run, {"node_id": node.id, "entry": entry, "state": STATE_PENDING, FRESH_KEY: True,
                      **({THEN_KEY: following} if following else {})})
    await continue_on_device(db, run)
    return thread


__all__ = ["continue_in_new_thread"]
