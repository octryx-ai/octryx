"""Device jobs: turns, sequenced events, owner-only approvals and stop.

A job is sticky per chat thread: every message of the thread is a turn of the same job while the target
(device, folder, profile) stays the same; a changed target or a finished job starts a new job (which resumes the
previous Claude Code session on the same target). Turns, stop requests and approval decisions are written here
and delivered by the channel tick (``jobs_channel``); the device's events come back through
:func:`apply_event` exactly once per ``seq``.

Hard invariants (code, not policy): only the job's owner decides its approvals or stops it; a decision after
``expires_at`` is refused (``approval_expired``) and the row is expired with a compare-and-set, so a late click
can never allow.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, UserDevice
from ...time_utils import utc_now
from .job_events import _continue_run
from .job_state import (
    ACTIVE_STATUSES,
    EFFORTS,
    MAX_PROMPT_CHARS,
    OFFLINE_GRACE,
    PERMISSION_MODES,
    REASON_JOB_BUSY,
    REASON_JOB_NOT_FOUND,
    REASON_JOB_NOT_RUNNING,
    STATUS_IDLE,
    STATUS_LOST,
    STATUS_OFFERED,
    DeviceJobError,
    _audit,
)


async def active_job_count(db: AsyncSession, device_id: str) -> int:
    return int((await db.execute(
        select(func.count()).select_from(DeviceJob).where(DeviceJob.device_id == device_id,
                                                          DeviceJob.status.in_(ACTIVE_STATUSES))
    )).scalar_one())


async def counted_job_count(db: AsyncSession, device_id: str) -> int:
    """The active jobs that take one of the device's parallel slots: all but a team's platform turns on its run's
    main thread (``workflow_runs.teamwork.slots``: the git work and the coordinator's answers while items run)."""
    from ..workflow_runs.teamwork.slots import slot_free_sessions

    sessions = [str(row) for row in (await db.execute(
        select(DeviceJob.session_id).where(DeviceJob.device_id == device_id, DeviceJob.status.in_(ACTIVE_STATUSES))
    )).scalars().all()]
    free = await slot_free_sessions(db, sessions) if sessions else set()
    return sum(1 for session_id in sessions if session_id not in free)


async def thread_job(db: AsyncSession, session_id: str) -> DeviceJob | None:
    """The thread's latest job (open or not)."""
    return (await db.execute(
        select(DeviceJob).where(DeviceJob.session_id == session_id).order_by(DeviceJob.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def mark_lost_jobs(db: AsyncSession, *, device_id: str | None = None) -> list[DeviceJob]:
    """Running jobs of a device that stayed away longer than the grace become ``device_lost``."""
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
) -> DeviceJob:
    """A new turn for the thread: on its open job when the target is unchanged, else on a new job. Flushes.

    ``fresh_session``: the turn starts a new Claude Code conversation instead of resuming the job's (a workflow run's
    phase pass: its context is the run contract and the repository, not the history of earlier phases; otherwise
    every call resends ~60k tokens of earlier phases).

    ``resume_session_id``: the turn resumes exactly this Claude Code conversation of the same device, folder and
    profile (a workflow run's next pass of the same phase continues that phase's own session even when another turn,
    such as the launcher's pipeline turn, ran on the job in between).

    ``model`` (already checked by the caller; ``""``: the device's default) belongs to the turn, not the target:
    a changed model continues the same job and Claude Code session from this turn on."""
    previous = await thread_job(db, session_id)
    same_target = previous is not None and (previous.device_id, previous.folder, previous.profile) == (
        device.id, folder, profile)
    if previous is not None and previous.status in ACTIVE_STATUSES:
        raise DeviceJobError(REASON_JOB_BUSY, 409)
    if same_target and previous.status == STATUS_IDLE:
        job = previous
    else:
        job = DeviceJob(device_id=device.id, owner_user_id=owner_user_id, session_id=session_id,
                        workspace_id=workspace_id, folder=folder, profile=profile,
                        resume_claude_session_id=previous.claude_session_id if same_target else None)
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


async def owned_job(db: AsyncSession, *, job_id: str, user_id: str) -> DeviceJob:
    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or job.owner_user_id != user_id:
        raise DeviceJobError(REASON_JOB_NOT_FOUND, 404)
    return job


async def request_stop(db: AsyncSession, job: DeviceJob, *, actor_id: str) -> None:
    if job.status not in ACTIVE_STATUSES:
        raise DeviceJobError(REASON_JOB_NOT_RUNNING, 409)
    if job.turn_state == "pending":
        # Not delivered yet: nothing runs on the device, the turn simply ends here.
        job.turn_state, job.status, job.status_reason = "cancelled", STATUS_IDLE, "stopped_by_owner"
    else:
        job.stop_state = "pending"
    _audit(db, actor_id=actor_id, action="device.job.stop_requested", job=job, details={"turn_id": job.turn_id})
    await db.flush()


async def stop_active_jobs(db: AsyncSession, *, actor_id: str, reason: str,
                           workspace_id: str | None = None) -> list[DeviceJob]:
    """A kill switch went off (platform, Workspace): every running turn in scope stops. Flushes."""
    query = select(DeviceJob).where(DeviceJob.status.in_(ACTIVE_STATUSES))
    if workspace_id is not None:
        query = query.where(DeviceJob.workspace_id == workspace_id)
    jobs = list((await db.execute(query)).scalars().all())
    for job in jobs:
        if job.turn_state == "pending":
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
]
