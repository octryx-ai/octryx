"""The coding engine of a device job, fixed at its first offer (``agent_gateway/engine_policy``).

A job's session can only be continued by the engine that started it, so the engine is decided once:

- a take-over of a Claude Code profile on the Mac (``local:<name>``) is Claude Code by nature;
- a job with a session (its own ``claude_session_id``, which the epic chain sets for the next story, or
  ``resume_claude_session_id``) takes the engine of the job that ran that session; a session no other job knows is
  Claude Code (e.g. a Mac session continued from the phone);
- any other job gets the owner's effective engine in its Workspace.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob
from ..agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES
from ..agent_gateway.engine_policy import effective_engine


async def _engine_of_session(db: AsyncSession, session_id: str, *, other_than: str | None = None) -> str | None:
    # The job that ran the session, or one that continued it (a resumed Codex thread keeps its id).
    query = select(DeviceJob.engine).where(
        or_(DeviceJob.claude_session_id == session_id, DeviceJob.resume_claude_session_id == session_id,
            DeviceJob.resume_claude_session_id == f"fork:{session_id}"),
        DeviceJob.engine.is_not(None))
    if other_than:
        query = query.where(DeviceJob.id != other_than)
    return (await db.execute(query.order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one_or_none()


async def job_engine(db: AsyncSession, job: DeviceJob) -> str:
    """The job's engine; stores it on the job the first time (the caller commits)."""
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
        engine = (await effective_engine(db, user_id=job.owner_user_id, workspace_id=job.workspace_id)).engine
    job.engine = engine
    return engine


__all__ = ["job_engine"]
