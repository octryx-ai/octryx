"""Cross-process scheduler coordination: the owner lease and the schedules it applied."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Index, String

from ...db import Base


class SchedulerOwnerLease(Base):
    """The schedule registrant's lease; instants are measured on the database clock."""

    __tablename__ = "scheduler_owner_leases"

    id = Column(String(40), primary_key=True)
    owner_process_id = Column(String(36), nullable=False)
    epoch = Column(BigInteger, nullable=False)
    acquired_at = Column(DateTime, nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class SchedulerJobApplication(Base):
    """What the owner of ``owner_epoch`` applied for one schedule (``scheduler:<id>`` or ``task:<id>``)."""

    __tablename__ = "scheduler_job_applications"
    __table_args__ = (Index("ix_scheduler_job_applications_owner_epoch", "owner_epoch"),)

    job_key = Column(String(80), primary_key=True)
    owner_epoch = Column(BigInteger, nullable=False)
    applied_fingerprint = Column(String(64), nullable=False)
    # registered | invalid_schedule
    status = Column(String(20), nullable=False)
    next_run_at = Column(DateTime, nullable=True)
    timezone = Column(String(80), nullable=True)
    applied_at = Column(DateTime, nullable=False)


__all__ = ["SchedulerJobApplication", "SchedulerOwnerLease"]
