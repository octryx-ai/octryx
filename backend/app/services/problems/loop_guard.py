"""Loop guard: a run that loops is paused, and its people learn it on their phone."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import ACTIVE_STATUSES

from ...models import DeviceJob, WorkflowRun, WorkflowRunSession
from ...time_utils import utc_now
from ..workflow_runs.limits import pause_run
from ..workflow_runs.records import WorkflowRunError, lock_run
from ..workflow_runs.states import STATUS_RUNNING, STATUS_WAITING
from . import activity
from .model import CollectContext

REASON = "loop_detected"


async def _stop_jobs(db: AsyncSession, run: WorkflowRun) -> list[str]:
    from ..devices.jobs import request_stop

    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id)
    jobs = list((await db.execute(select(DeviceJob).where(
        DeviceJob.session_id.in_(sessions), DeviceJob.status.in_(ACTIVE_STATUSES)))).scalars())
    stopped = []
    for job in jobs:
        try:
            await request_stop(db, job, actor_id=job.owner_user_id)
            stopped.append(job.id)
        except Exception:  # noqa: BLE001 - a job that ended in between needs no stop
            continue
    return stopped


def loop_message(item: str, count: int, minutes: int) -> str:
    return (f"Loop detected: item {item} was dispatched {count} times in {minutes} minutes without moving on. "
            "The run was paused automatically; fix the cause, then Continue resumes it.")


async def pause_looping_runs(db: AsyncSession, *, now=None) -> list[dict[str, Any]]:
    minutes = int(activity.LOOP_WINDOW.total_seconds() // 60)
    paused: list[dict[str, Any]] = []
    for run, found in await activity.looping_runs(db, CollectContext(now=now or utc_now())):
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue
        if run.status not in (STATUS_RUNNING, STATUS_WAITING):
            continue
        await pause_run(db, run, reason=REASON, actor_id=None, detail={
            "message": loop_message(found["item"], found["count"], minutes), "code": REASON,
            "item": found["item"], "count": found["count"], "iteration": found.get("iteration"),
            "window_minutes": minutes, "resume": {"kind": "restart", "node_id": run.current_node_id},
        })
        paused.append({"run_id": run.id, "item": found["item"], "count": found["count"],
                       "stopped_device_jobs": await _stop_jobs(db, run)})
    await db.flush()
    return paused


__all__ = ["REASON", "loop_message", "pause_looping_runs"]
