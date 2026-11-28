"""Device jobs: turns, sequenced events, owner-only approvals and stop."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, UserDevice
from ...time_utils import utc_now
from .engine_state import resumable_from_snapshot
from .job_events import _continue_run
from .job_state import (
    ACTIVE_STATUSES,
    BUSY_STATUSES,
    EFFORTS,
    MAX_PROMPT_CHARS,
    OFFLINE_GRACE,
    PERMISSION_MODES,
    REASON_CANCELLED,
    REASON_JOB_BUSY,
    REASON_JOB_NOT_FOUND,
    REASON_JOB_NOT_RUNNING,
    STATUS_CLOSED,
    STATUS_IDLE,
    STATUS_LOST,
    STATUS_OFFERED,
    STATUS_WAITING,
    DeviceJobError,
    _audit,
)
from .runner_pool import RUNNER_SERVICE_KIND
from .runner_tenant import close_other_tenants


async def active_job_count(db: AsyncSession, device_id: str) -> int:
    return int((await db.execute(
        select(func.count()).select_from(DeviceJob).where(DeviceJob.device_id == device_id,
                                                          DeviceJob.status.in_(ACTIVE_STATUSES))
    )).scalar_one())


async def counted_job_count(db: AsyncSession, device_id: str) -> int:
    from ..workflow_runs.teamwork.slots import slot_free_sessions

    sessions = [str(row) for row in (await db.execute(
        select(DeviceJob.session_id).where(DeviceJob.device_id == device_id, DeviceJob.status.in_(ACTIVE_STATUSES))
    )).scalars().all()]
    free = await slot_free_sessions(db, sessions) if sessions else set()
    return sum(1 for session_id in sessions if session_id not in free)


async def thread_job(db: AsyncSession, session_id: str) -> DeviceJob | None:
    return (await db.execute(
        select(DeviceJob).where(DeviceJob.session_id == session_id,
                                or_(DeviceJob.device_id.is_not(None), DeviceJob.status == STATUS_WAITING))
        .order_by(DeviceJob.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def mark_lost_jobs(db: AsyncSession, *, device_id: str | None = None) -> list[DeviceJob]:
    cutoff = utc_now() - OFFLINE_GRACE
    query = select(DeviceJob).where(DeviceJob.status.in_(ACTIVE_STATUSES), DeviceJob.disconnected_at.is_not(None),
                                    DeviceJob.disconnected_at <= cutoff)
    if device_id is not None:
        query = query.where(DeviceJob.device_id == device_id)
    lost = list((await db.execute(query)).scalars().all())
    for job in lost:
        job.status, job.status_reason, job.finished_at = STATUS_LOST, "device_offline", utc_now()
        _audit(db, actor_id=job.owner_user_id, action="device.job.lost", job=job, details={})
    for job in lost:
        await _continue_run(db, job, failed=True)
    await db.flush()
    return lost


async def start_turn(
    db: AsyncSession, *, owner_user_id: str, device: UserDevice, session_id: str, workspace_id: str | None,
    folder: str, profile: str, prompt: str, policy_decision_id: str | None = None, model: str = "",
    permission_mode: str = "", effort: str = "", fresh_session: bool = False, resume_session_id: str = "",
    waiting: DeviceJob | None = None,
) -> DeviceJob:
    previous = await thread_job(db, session_id) if waiting is None else await _ran_before(db, waiting)
    same_target = previous is not None and (previous.device_id, previous.folder, previous.profile) == (
        device.id, folder, profile)
    if previous is not None and previous.status in BUSY_STATUSES:
        raise DeviceJobError(REASON_JOB_BUSY, 409)
    if device.service_kind == RUNNER_SERVICE_KIND:
        await close_other_tenants(db, device.id, owner_user_id=owner_user_id, workspace_id=workspace_id)
    if waiting is not None:  # the turn that waited for a runner becomes the job, so its id stays
        carried = previous.claude_session_id if previous is not None else None
        if not same_target:
            carried = await resumable_from_snapshot(db, session_id, carried or "") or None
        job = waiting
        job.device_id, job.folder, job.profile, job.resume_claude_session_id = device.id, folder, profile, carried
        _audit(db, actor_id=owner_user_id, action="device.job.created", job=job,
               details={"profile": profile, "policy_decision_id": policy_decision_id, "waited": True})
    elif same_target and previous.status == STATUS_IDLE:
        job = previous
    else:
        carried = previous.claude_session_id if previous is not None else None
        if not same_target:
            # Another target continues the session only from the files the platform holds (``engine_state``).
            carried = await resumable_from_snapshot(db, session_id, carried or "") or None
        job = DeviceJob(device_id=device.id, owner_user_id=owner_user_id, session_id=session_id,
                        workspace_id=workspace_id, folder=folder, profile=profile, resume_claude_session_id=carried)
        db.add(job)
        await db.flush()
        _audit(db, actor_id=owner_user_id, action="device.job.created", job=job,
               details={"profile": profile, "policy_decision_id": policy_decision_id})
    if fresh_session or resume_session_id:
        job.claude_session_id, job.resume_claude_session_id = None, (resume_session_id[:80] or None)
    job.status, job.status_reason = STATUS_OFFERED, None
    job.turn_id, job.turn_prompt, job.turn_state = uuid.uuid4().hex, prompt[:MAX_PROMPT_CHARS], "pending"
    job.turn_count = int(job.turn_count or 0) + 1
    if (job.turn_model or "") != model:
        job.turn_model, job.model = model or None, None  # the device reports the effective model again
    job.turn_permission_mode = permission_mode if permission_mode in PERMISSION_MODES else None
    job.turn_effort = effort if effort in EFFORTS else None
    job.stop_state, job.disconnected_at, job.finished_at = None, None, None
    job.policy_decision_id = policy_decision_id or job.policy_decision_id
    await db.flush()
    return job


async def _ran_before(db: AsyncSession, waiting: DeviceJob) -> DeviceJob | None:
    return (await db.execute(
        select(DeviceJob).where(DeviceJob.session_id == waiting.session_id, DeviceJob.id != waiting.id,
                                DeviceJob.device_id.is_not(None))
        .order_by(DeviceJob.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def wait_for_runner(db: AsyncSession, *, owner_user_id: str, session_id: str, workspace_id: str | None,
                          prompt: str, model: str = "", permission_mode: str = "", effort: str = "") -> DeviceJob:
    previous = await thread_job(db, session_id)
    if previous is not None and previous.status in BUSY_STATUSES:
        raise DeviceJobError(REASON_JOB_BUSY, 409)
    job = DeviceJob(device_id=None, owner_user_id=owner_user_id, session_id=session_id, workspace_id=workspace_id,
                    folder="", profile="governed", status=STATUS_WAITING, turn_prompt=prompt[:MAX_PROMPT_CHARS],
                    turn_model=model or None,
                    turn_permission_mode=permission_mode if permission_mode in PERMISSION_MODES else None,
                    turn_effort=effort if effort in EFFORTS else None)
    db.add(job)
    await db.flush()
    _audit(db, actor_id=owner_user_id, action="device.job.waiting_runner", job=job, details={})
    await db.flush()
    return job


def _cancel_wait(job: DeviceJob, reason: str) -> None:
    job.status, job.status_reason, job.finished_at = STATUS_CLOSED, reason, utc_now()


async def owned_job(db: AsyncSession, *, job_id: str, user_id: str) -> DeviceJob:
    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or job.owner_user_id != user_id:
        raise DeviceJobError(REASON_JOB_NOT_FOUND, 404)
    return job


async def request_stop(db: AsyncSession, job: DeviceJob, *, actor_id: str) -> None:
    if job.status not in BUSY_STATUSES:
        raise DeviceJobError(REASON_JOB_NOT_RUNNING, 409)
    if job.status == STATUS_WAITING:
        _cancel_wait(job, REASON_CANCELLED)
    elif job.turn_state == "pending":
        # Not delivered yet: nothing runs on the device, the turn simply ends here.
        job.turn_state, job.status, job.status_reason = "cancelled", STATUS_IDLE, "stopped_by_owner"
    else:
        job.stop_state = "pending"
    _audit(db, actor_id=actor_id, action="device.job.stop_requested", job=job, details={"turn_id": job.turn_id})
    await db.flush()


async def stop_active_jobs(db: AsyncSession, *, actor_id: str, reason: str,
                           workspace_id: str | None = None) -> list[DeviceJob]:
    query = select(DeviceJob).where(DeviceJob.status.in_(BUSY_STATUSES))
    if workspace_id is not None:
        query = query.where(DeviceJob.workspace_id == workspace_id)
    jobs = list((await db.execute(query)).scalars().all())
    for job in jobs:
        if job.status == STATUS_WAITING:
            _cancel_wait(job, reason)
        elif job.turn_state == "pending":
            job.turn_state, job.status, job.status_reason = "cancelled", STATUS_IDLE, reason
        else:
            job.stop_state = "pending"
        _audit(db, actor_id=actor_id, action="device.job.stop_requested", job=job, details={"reason": reason})
    await db.flush()
    return jobs


__all__ = [
    "active_job_count",
    "mark_lost_jobs",
    "counted_job_count",
    "owned_job",
    "request_stop",
    "start_turn",
    "stop_active_jobs",
    "thread_job",
    "wait_for_runner",
]
