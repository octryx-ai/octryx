"""Stopping the run's device items: an abort or leaving the ``parallel_work`` node stops their jobs and the git work."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunSession
from ..records import record_event
from . import ROLE_ITEM, RUNNING, work_of
from .device_work_state import RELEASED_KEPT, _is_turn, _set_state, _state


async def left_node(db: AsyncSession, run: WorkflowRun, *, actor_id: str | None) -> None:
    from .scheduler import _store

    work = work_of(run)
    items = {key: dict(value) for key, value in dict(work.get("items") or {}).items()}
    running = [key for key, item in items.items() if item.get("status") == RUNNING]
    if running or _state(run).get("sent") or _state(run).get("sequential_job"):
        await stop_jobs(db, run, actor_id=actor_id)
    if not running:
        return
    for key in running:
        items[key].update(status="pending", job_id=None, reason="stopped: the run left the parallel work step")
    work["items"] = items
    _store(run, work)
    record_event(db, run, "work_items_stopped", node_id=work.get("node_id"), detail={"items": running})


async def stop_jobs(db: AsyncSession, run: WorkflowRun, *, actor_id: str | None) -> list[str]:
    from sqlalchemy import select

    from app.services.devices.job_state import ACTIVE_STATUSES

    from ....models import DeviceJob
    from ...devices.jobs import request_stop

    threads = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id,
                                                          WorkflowRunSession.role == ROLE_ITEM)
    state = _state(run)
    main_turns = [dict(entry) for entry in (state.get("sent"), state.get("sequential_job")) if entry]
    main_jobs = [str(entry.get("job_id") or "") for entry in main_turns]
    jobs = (await db.execute(select(DeviceJob).where(
        DeviceJob.status.in_(tuple(ACTIVE_STATUSES)),
        DeviceJob.session_id.in_(threads) | DeviceJob.id.in_(main_jobs)))).scalars().all()
    stopped = []
    for job in jobs:
        if job.id in main_jobs and not any(_is_turn(entry, job) for entry in main_turns):
            continue  # the main thread's job runs another turn now (the coordinator's): never teamwork's to stop
        if job.stop_state or job.turn_state == "cancelled":
            continue
        await request_stop(db, job, actor_id=actor_id or job.owner_user_id)
        stopped.append(job.id)
    _release_main_turns(run)
    return stopped


def _release_main_turns(run: WorkflowRun) -> None:
    # Released turn ids stay known, so their end is still teamwork's own and never the run's phase turn.
    state = _state(run)
    sent, sequential = dict(state.get("sent") or {}), dict(state.get("sequential_job") or {})
    if not sent and not sequential:
        return
    released = [*list(state.get("released") or []),
                *[{"job_id": entry.get("job_id"), "turn_id": entry.get("turn_id")} for entry in (sent, sequential)
                  if entry.get("turn_id")]][-RELEASED_KEPT:]
    _set_state(run, {**state, "sent": None, "sequential_job": None, "released": released,
                     "ops": [*list(sent.get("ops") or []), *list(state.get("ops") or [])]})
