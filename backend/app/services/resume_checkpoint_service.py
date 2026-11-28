"""Run resumption service — recovers sessions from active ContextCheckpoint records."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ContextCheckpoint, ResumeCheckpoint, Session
from ..models.runtime.durable_runtime import (
    RECOVERY_POLICY_AUTO_RETRY,
    RECOVERY_POLICY_MANUAL_RESUME,
)
from ..time_utils import utc_now

logger = logging.getLogger(__name__)


async def create_resume_checkpoint(
    db: AsyncSession,
    *,
    session_id: str,
    checkpoint_id: str,
    max_resume_attempts: int = 3,
) -> ResumeCheckpoint:
    # Idempotent: return existing if already created
    existing = await db.execute(
        select(ResumeCheckpoint).where(
            ResumeCheckpoint.session_id == session_id,
            ResumeCheckpoint.checkpoint_id == checkpoint_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    rc = ResumeCheckpoint(
        id=str(uuid.uuid4()),
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        status="pending",
        resume_attempt_count=0,
        max_resume_attempts=max_resume_attempts,
    )
    db.add(rc)
    await db.flush()
    return rc


async def get_active_checkpoint_for_session(
    db: AsyncSession,
    *,
    session_id: str,
) -> ContextCheckpoint | None:
    result = await db.execute(
        select(ContextCheckpoint)
        .where(
            ContextCheckpoint.session_id == session_id,
            ContextCheckpoint.status == "active",
        )
        .order_by(ContextCheckpoint.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def can_resume(resume_checkpoint: ResumeCheckpoint) -> bool:
    if resume_checkpoint.status in {"resumed", "failed", "exhausted"}:
        return False
    if resume_checkpoint.resume_attempt_count >= resume_checkpoint.max_resume_attempts:
        return False
    return True


async def attempt_resume(
    db: AsyncSession,
    session: Session,
    checkpoint: ContextCheckpoint,
    *,
    resume_checkpoint: ResumeCheckpoint | None = None,
) -> ResumeCheckpoint:
    if resume_checkpoint is None:
        resume_checkpoint = await create_resume_checkpoint(
            db, session_id=session.id, checkpoint_id=checkpoint.id
        )

    if not can_resume(resume_checkpoint):
        resume_checkpoint.status = "exhausted"
        resume_checkpoint.last_error = "Resume policy exhausted"
        await db.commit()
        return resume_checkpoint

    resume_checkpoint.resume_attempt_count = (resume_checkpoint.resume_attempt_count or 0) + 1
    resume_checkpoint.status = "in_progress"
    resume_checkpoint.last_resume_at = utc_now()
    resume_checkpoint.last_error = None
    await db.commit()
    return resume_checkpoint


async def mark_resume_success(
    db: AsyncSession,
    resume_checkpoint: ResumeCheckpoint,
) -> ResumeCheckpoint:
    resume_checkpoint.status = "resumed"
    await db.commit()
    return resume_checkpoint


async def mark_resume_failed(
    db: AsyncSession,
    resume_checkpoint: ResumeCheckpoint,
    error: str,
) -> ResumeCheckpoint:
    resume_checkpoint.status = "failed"
    resume_checkpoint.last_error = str(error)[:500]
    await db.commit()
    return resume_checkpoint


async def find_all_recoverable_sessions(
    db: AsyncSession,
    limit: int = 100,
) -> list[tuple[Session, ContextCheckpoint]]:
    result = await db.execute(
        select(Session, ContextCheckpoint)
        .join(
            ContextCheckpoint,
            ContextCheckpoint.session_id == Session.id,
        )
        .where(
            Session.run_status == "in_progress",
            ContextCheckpoint.status == "active",
        )
        .where(Session.recovery_policy.in_([RECOVERY_POLICY_AUTO_RETRY, RECOVERY_POLICY_MANUAL_RESUME]))
        .limit(limit)
    )
    return list(result.all())


def get_session_recovery_policy(session: Session) -> str:
    # Falls back to ``manual_resume``.
    return str(session.recovery_policy or RECOVERY_POLICY_MANUAL_RESUME).strip().lower()


