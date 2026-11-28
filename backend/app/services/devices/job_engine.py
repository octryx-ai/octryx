"""The coding engine of a device job, fixed at its first offer (``agent_gateway/engine_policy``)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, UserDevice
from ..agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES
from ..agent_gateway.engine_policy import SOURCE_PLATFORM, effective_engine
from .runner_pool import RUNNER_SERVICE_KIND
from .seat_engines import runs_engine


async def _engine_of_session(db: AsyncSession, session_id: str, *, other_than: str | None = None) -> str | None:
    # The job that ran the session, or one that continued it (a resumed Codex thread keeps its id).
    query = select(DeviceJob.engine).where(
        or_(DeviceJob.claude_session_id == session_id, DeviceJob.resume_claude_session_id == session_id,
            DeviceJob.resume_claude_session_id == f"fork:{session_id}"),
        DeviceJob.engine.is_not(None))
    if other_than:
        query = query.where(DeviceJob.id != other_than)
    return (await db.execute(query.order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one_or_none()


async def _default_engine(db: AsyncSession, job: DeviceJob) -> str:
    setting = await effective_engine(db, user_id=job.owner_user_id, workspace_id=job.workspace_id)
    if setting.source != SOURCE_PLATFORM:
        return setting.engine  # chosen by the Workspace or the person: a runner without it refuses the turn
    device = await db.get(UserDevice, job.device_id) if job.device_id else None
    if device is None or device.service_kind != RUNNER_SERVICE_KIND or runs_engine(device, setting.engine):
        return setting.engine
    return next((engine for engine in setting.allowed if runs_engine(device, engine)), setting.engine)


async def job_engine(db: AsyncSession, job: DeviceJob) -> str:
    if job.engine in ENGINES:
        return job.engine
    resume = (job.resume_claude_session_id or "").removeprefix("fork:")
    session = job.claude_session_id or resume
    if str(job.profile or "").startswith("local:"):
        engine = ENGINE_CLAUDE_CODE  # a take-over of a Claude Code profile on the Mac
    elif session:
        # The session's engine, from the job that ran it: the epic chain gives the next story's job the epic's
        # session as its own (story 2 of a Codex epic must not resume the Codex thread as Claude Code). A
        # session no other job knows is the Mac's own Claude Code session.
        engine = await _engine_of_session(db, session, other_than=job.id) or ENGINE_CLAUDE_CODE
    else:
        engine = await _default_engine(db, job)
    job.engine = engine
    return engine


__all__ = ["job_engine"]
