"""Runtime models for durable execution: distributed locks and resume checkpoints."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class DistributedLock(Base):
    """DB-backed distributed lock replacing process-local asyncio.Lock dicts.

    Stored in the main database (SQLite for dev, Postgres for EKS). Uses
    owner_id + expires_at for safe lock release — only the owner can release.
    """

    __tablename__ = "distributed_locks"
    __table_args__ = (
        Index("ix_distributed_locks_key", "lock_key"),
        Index("ix_distributed_locks_expires", "expires_at"),
        Index("ix_distributed_locks_owner", "owner_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    lock_key = Column(String(255), nullable=False, index=True)
    owner_id = Column(String(255), nullable=False, index=True)  # worker/process/thread ID
    acquired_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    metadata_json = Column(JSON, default=dict)
    released_at = Column(DateTime, nullable=True)

    # Well-known lock keys (documented for safe reuse)
    LOCK_KEY_CHAT_TURN = "session:{session_id}:turn_lock"
    LOCK_KEY_SUB_AGENT_GROUP = "group:{group_id}:lock"
    LOCK_KEY_QUEUE_CLAIM = "queue:{queue_id}:claim"
    LOCK_KEY_ORCHESTRATOR = "orchestrator:{run_id}:lock"


class ResumeCheckpoint(Base):
    """Tracks attempts to resume a session from a ContextCheckpoint.

    Enables recovery_policy enforcement (auto_retry | manual_resume | fail)
    and prevents infinite retry loops by tracking attempt counts.
    """

    __tablename__ = "resume_checkpoints"
    __table_args__ = (
        Index("ix_resume_checkpoint_session", "session_id"),
        Index("ix_resume_checkpoint_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    checkpoint_id = Column(String(36), ForeignKey("context_checkpoints.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending | in_progress | resumed | failed | exhausted
    resume_attempt_count = Column(Integer, nullable=False, default=0)
    max_resume_attempts = Column(Integer, nullable=False, default=3)
    last_resume_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    session = relationship("Session")
    checkpoint = relationship("ContextCheckpoint")


# Session recovery policies
RECOVERY_POLICY_AUTO_RETRY = "auto_retry"
RECOVERY_POLICY_MANUAL_RESUME = "manual_resume"
RECOVERY_POLICY_FAIL = "fail"
RECOVERY_POLICIES = {RECOVERY_POLICY_AUTO_RETRY, RECOVERY_POLICY_MANUAL_RESUME, RECOVERY_POLICY_FAIL}
