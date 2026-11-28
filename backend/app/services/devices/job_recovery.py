"""Device turns that will never finish on their own: stalled turns end as failed."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, DeviceJob, DeviceJobApproval
from ...time_utils import ensure_utc, utc_now
from .device_runs_keys import DEFAULTS

REASON_TURN_STALLED = "turn_stalled"
DELIVERED_TURN_STATES = ("sent", "accepted")
# A turn the device has not accepted yet while its run waits for a launcher step (the CI pipeline, the folder's
# setup) sends no event until that step ends: setup up to 15 minutes, then the tests and their re-runs. Without
# this, a pipeline longer than the 10-minute default was ended as stalled and its run paused.
LAUNCHER_STEP_MINUTES = 45
LAUNCHER_STEP_ACTIONS = ("pipeline.run", "workspace.prepare")


async def _launcher_step(db: AsyncSession, job: DeviceJob) -> bool:
    if job.turn_state != "sent" or not job.session_id:
        return False
    from ..workflow_runs.graph import graph_for_run
    from ..workflow_runs.records import active_run_for_session

    run = await active_run_for_session(db, job.session_id)
    if run is None or not run.current_node_id:
        return False
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    return node is not None and str(dict(node.config or {}).get("action") or "") in LAUNCHER_STEP_ACTIONS


async def _stale_minutes(db: AsyncSession, workspace_id: str | None, cache: dict[str | None, int]) -> int:
    if workspace_id not in cache:
        from .workspace_policy import workspace_device_setting

        value = await workspace_device_setting(db, workspace_id, "stale_turn_minutes")
        cache[workspace_id] = value if type(value) is int and value > 0 else DEFAULTS["stale_turn_minutes"]
    return cache[workspace_id]


async def fail_stalled_turns(db: AsyncSession, *, device_id: str | None = None,
                             now: Any = None) -> list[DeviceJob]:
    current = ensure_utc(now or utc_now())
    waiting = exists().where(DeviceJobApproval.job_id == DeviceJob.id, DeviceJobApproval.status == "pending")
    query = select(DeviceJob).where(
        DeviceJob.status.in_(("offered", "running")), DeviceJob.turn_state.in_(DELIVERED_TURN_STATES),
        DeviceJob.disconnected_at.is_(None), ~waiting,
        # The shortest allowed timeout; each job is then checked against its Workspace's own setting.
        DeviceJob.updated_at <= (current - timedelta(minutes=1)).replace(tzinfo=None),
    )
    if device_id is not None:
        query = query.where(DeviceJob.device_id == device_id)
    cache: dict[str | None, int] = {}
    stalled: list[DeviceJob] = []
    for job in (await db.execute(query)).scalars().all():
        minutes = await _stale_minutes(db, job.workspace_id, cache)
        if ensure_utc(job.updated_at) > current - timedelta(minutes=minutes):
            continue
        if minutes < LAUNCHER_STEP_MINUTES and await _launcher_step(db, job) and \
                ensure_utc(job.updated_at) > current - timedelta(minutes=LAUNCHER_STEP_MINUTES):
            continue
        job.status, job.turn_state, job.status_reason = "idle", "failed", REASON_TURN_STALLED
        job.stop_state = "pending"  # the device stops the turn should it still run
        db.add(AuditLog(user_id=job.owner_user_id, session_id=job.session_id, action="device.job.turn_stalled",
                        resource_type="device_job", resource_id=job.id,
                        project_id=job.workspace_id,
                        details={"device_id": job.device_id, "turn_id": job.turn_id, "stale_turn_minutes": minutes}))
        stalled.append(job)
    await db.flush()
    from ..workflow_runs.octryx.continuation import continue_after_device_turn

    for job in stalled:
        # A pending next phase starts after a stalled turn; a stalled phase turn pauses its run.
        await continue_after_device_turn(db, job.session_id, failure=REASON_TURN_STALLED)
    return stalled


__all__ = ["REASON_TURN_STALLED", "fail_stalled_turns"]
