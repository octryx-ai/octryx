"""Teamwork items on the run's device or server runner."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..records import record_event
from . import EXECUTOR_DEVICE, EXECUTOR_SEQUENTIAL, RUNNING, item_marker, work_of
from .device_work_state import (
    EVENT_SEQUENTIAL,
    FALLBACK_NO_DEVICE,
    FALLBACK_NOT_PARALLEL,
    FALLBACK_ONE_SLOT,
    _is_turn,
    _main_thread,
    _parallel_node,
    _set_state,
    _state,
)
from .item_sessions import _item
from .item_threads import _start_item_thread, _start_sequential, sessions_key
from .work_git import flush, queue_op


async def fallback_reason(db: AsyncSession, run: WorkflowRun, target: dict[str, Any]) -> str:
    from ....models import UserDevice
    from ...devices.runner_pool import RUNNER_SERVICE_KIND

    if _state(run).get("fallback"):
        return str(_state(run)["fallback"])
    node = await _parallel_node(db, run)
    if node is not None and dict(node.config or {}).get("parallel") is False:
        return FALLBACK_NOT_PARALLEL
    device = await db.get(UserDevice, str(target.get("device_id") or ""))
    if device is None:
        return FALLBACK_ONE_SLOT
    # A runner's one slot is the pool's unit of scale, not a person's limit: its items still get their own worktree
    # branches and run one after another.
    if int(device.max_parallel_jobs or 1) < 2 and device.service_kind != RUNNER_SERVICE_KIND:
        return FALLBACK_ONE_SLOT
    return ""


class DeviceExecutor:
    def __init__(self, *, slots: int, sequential: str = "") -> None:
        self.slots = slots
        self.sequential = sequential
        self.name = EXECUTOR_SEQUENTIAL if sequential else EXECUTOR_DEVICE

    def capacity(self, run: Any) -> int | None:
        if self.sequential or _state(run).get("fallback"):
            return 1
        return max(1, self.slots)

    async def start(self, db: AsyncSession, run: WorkflowRun, item: dict[str, Any]) -> dict[str, Any]:
        if self.sequential or _state(run).get("fallback"):
            return await _start_sequential(db, run, item)
        branched = _branched_for_plan(run, item["id"])
        if not branched:
            # After its merge conflicted, the item's branch gets the story's current work merged in.
            queue_op(run, "branch", item["id"], sync=item["id"] in list(_state(run).get("resync") or []))
            await flush(db, run)
            return {"status": "pending", "reason": "branching"}
        return await _start_item_thread(db, run, item, branched)

    async def merge(self, db: AsyncSession, run: WorkflowRun, item: dict[str, Any]) -> None:
        if self.sequential or not dict(_state(run).get("branched") or {}).get(item["id"]):
            from .item_results import merge_reported

            await merge_reported(db, run, key=item["id"], merged=True)
            return
        queue_op(run, "merge", item["id"])
        await flush(db, run)

    async def finish(self, db: AsyncSession, run: WorkflowRun) -> None:
        state = _state(run)
        _set_state(run, {"seq": state.get("seq") or 0, **({"fallback": state["fallback"]}
                                                           if state.get("fallback") else {})})


def _branched_for_plan(run: WorkflowRun, key: str) -> dict[str, Any]:
    state = _state(run)
    branched = dict(state.get("branched") or {})
    entry = dict(branched.get(key) or {})
    current = work_of(run).get("plan_version")
    if not entry or entry.get("plan_version", current) == current:
        return entry
    branched.pop(key, None)
    _set_state(run, {**state, "branched": branched, "resync": sorted({*list(state.get("resync") or []), key})})
    return {}


async def executor_for(db: AsyncSession, run: WorkflowRun) -> DeviceExecutor:
    from ....models import UserDevice

    thread, target = await _main_thread(db, run)
    if thread is None or target is None:
        # Neither a device nor a server runner holds the run's thread (a terminal drives it): each item's start fails
        # with that reason and the coordinator decides.
        return DeviceExecutor(slots=1, sequential=FALLBACK_NO_DEVICE)
    reason = await fallback_reason(db, run, target)
    device = await db.get(UserDevice, str(target.get("device_id") or ""))
    if reason and not _state(run).get("fallback_recorded") == reason:
        record_event(db, run, EVENT_SEQUENTIAL, node_id=run.current_node_id, detail={"reason": reason})
        _set_state(run, {**_state(run), "fallback_recorded": reason})
    return DeviceExecutor(slots=int(getattr(device, "max_parallel_jobs", 0) or 1), sequential=reason)


async def _item_turn_ended(db: AsyncSession, run: WorkflowRun, key: str, session_id: str, failure: str | None,
                           said: str, *, refused: bool = False) -> None:
    from ..octryx.turn_failures import is_transient_failure
    from .item_results import item_finished, item_start_refused

    item = _item(run, key)
    if item.get("status") != RUNNING or str(item.get("session_id") or "") != session_id:
        return
    if refused:
        await item_start_refused(db, run, key=key, session_id=session_id, reason=str(failure or "rejected_by_device"))
        return
    words = " ".join(str(said or "").split())[:300]
    if failure:
        await item_finished(db, run, key=key, session_id=session_id, state="failed",
                            transient=is_transient_failure(failure, said),
                            reason=f"device_turn_{failure}" + (f": {words}" if words else ""))
        return
    await item_finished(db, run, key=key, session_id=session_id, state="failed",
                        reason="the item's turn ended without finishing it" + (f": {words}" if words else ""))


async def _remember_sequential_session(db: AsyncSession, run: WorkflowRun, key: str, job: Any) -> None:
    from ..octryx.phase_sessions import SESSIONS_KEY, _job_session

    node_id = str(work_of(run).get("node_id") or run.current_node_id)
    context = dict(run.context or {})
    sessions = {**dict(context.get(SESSIONS_KEY) or {}), sessions_key(node_id, key): {
        "node_id": node_id, "job_id": job.id, "turn_id": job.turn_id, "claude_session_id": _job_session(job),
        "device_id": job.device_id, "folder": job.folder, "profile": job.profile}}
    run.context = {**context, SESSIONS_KEY: sessions}


async def job_ended(db: AsyncSession, run: WorkflowRun, session_id: str, *, failure: str | None = None,
                    said: str = "") -> bool:
    from ...devices.jobs import thread_job
    from ..records import lock_run

    work = work_of(run)
    if not work:
        return False
    thread = await db.get(Session, session_id)
    job = await thread_job(db, session_id)
    if work.get("route") or run.current_node_id != work.get("node_id"):
        # The run left the parallel node: an item's job ending now is still teamwork's own, never the run's phase turn.
        return _own_job(run, thread, job)
    run = await lock_run(db, run)
    state = _state(run)
    handled = False
    refused = job is not None and job.turn_state == "rejected"
    if (marker := item_marker(thread)) is not None:
        await _item_turn_ended(db, run, str(marker["key"]), session_id, failure, said, refused=refused)
        handled = True
    elif _is_turn(state.get("sequential_job"), job):
        key = str(state["sequential_job"]["key"])
        await _remember_sequential_session(db, run, key, job)
        _set_state(run, {**_state(run), "sequential_job": None})
        await _item_turn_ended(db, run, key, session_id, failure, said, refused=refused)
        handled = True
    elif _is_turn(state.get("sent"), job):
        # The git work's job ended without its report (an error on the device): the ops go out again.
        sent = dict(state["sent"])
        record_event(db, run, "teamwork_git_unreported", node_id=run.current_node_id,
                     detail={"seq": sent.get("seq"), "failure": failure})
        _set_state(run, {**state, "sent": None, "ops": [*list(sent.get("ops") or []), *list(state.get("ops") or [])],
                         "unreported": int(state.get("unreported") or 0) + 1})
        handled = True
    await after_job(db, run)
    return handled


def _own_job(run: WorkflowRun, thread: Any, job: Any) -> bool:
    marker = item_marker(thread)
    if marker is not None and marker.get("run_id") == run.id:
        return True
    state = _state(run)
    released = [dict(entry) for entry in state.get("released") or [] if isinstance(entry, dict)]
    return any(_is_turn(entry, job) for entry in [state.get("sequential_job"), state.get("sent"), *released])


async def after_job(db: AsyncSession, run: WorkflowRun) -> None:
    from .scheduler import advance

    work = work_of(run)
    if not work or work.get("route") or run.current_node_id != work.get("node_id"):
        return
    if int(_state(run).get("unreported") or 0) < 3:  # a launcher that keeps failing never loops the device
        await flush(db, run)
    await advance(db, run)


__all__ = ["DeviceExecutor", "executor_for", "fallback_reason", "job_ended"]
