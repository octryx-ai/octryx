"""Cross-process scheduler coordination state.

The schedule rows (``schedulers`` and ``tasks.schedule``) stay the only source of truth. These two
tables record *who registers them* and *what that registrant has applied*:

* ``scheduler_owner_leases`` holds one row (``id='task-scheduler'``): the platform process that
  owns schedule registration, its fencing ``epoch`` and database-clock lease instants;
* ``scheduler_job_applications`` holds one row per registered or rejected schedule, written only
  by the owner under its current epoch: the content fingerprint it applied, the next run time it
  registered and that registration's time zone.

No host name, PID, token, credential or error text is stored. The owner's process id is the random
per-boot id of ``runtime_process_leases`` and is never exposed by the API.
"""

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
