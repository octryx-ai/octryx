"""A device job without an agent: pinned tools run on code the platform sent (the review bot's scan and
the check proof of From Correction to Check; ``services/devices/tool_jobs``).

A row is ``pending`` until the channel tick of one of its ``candidates`` (connected, with every tool of ``needs``)
claims and sends it (``sent``), ``done`` with the device's raw ``result``, or ``timeout`` / ``failed`` with a
``reason``. The code travels as archives (``DeviceToolJobArchive``): their bytes live here only until the tick offers
them to the claiming device (the API process serves them; the worker that made them may run in another container).
"""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String

from ...db import Base
from ...time_utils import utc_now


def tool_job_pk() -> str:
    return f"tj_{secrets.token_hex(10)}"


class DeviceToolJob(Base):
    __tablename__ = "device_tool_jobs"
    __table_args__ = (Index("ix_device_tool_jobs_state_created", "state", "created_at"),)

    id = Column(String(40), primary_key=True, default=tool_job_pk)
    purpose = Column(String(60), nullable=False)  # e.g. pr_review.scan, check_proof
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    workspace_id = Column(String(36), nullable=True)
    candidates = Column(JSON, nullable=False, default=list)  # device ids, the first connected one with the tools
    needs = Column(JSON, nullable=False, default=list)  # tool ids the device must report as available
    steps = Column(JSON, nullable=False, default=list)
    archives = Column(JSON, nullable=False, default=list)  # {name, sha256, bytes, skipped} (no bytes)
    on_done = Column(String(120), nullable=True)  # a registered callback name (``tool_jobs.CALLBACKS``)
    state = Column(String(20), nullable=False, default="pending")
    device_id = Column(String(40), nullable=True)
    reason = Column(String(300), nullable=True)
    result = Column(JSON, nullable=True)
    timeout_seconds = Column(Integer, nullable=False, default=600)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class DeviceToolJobArchive(Base):
    __tablename__ = "device_tool_job_archives"

    id = Column(String(40), primary_key=True, default=lambda: f"ta_{secrets.token_hex(10)}")
    job_id = Column(String(40), ForeignKey("device_tool_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    data = Column(LargeBinary, nullable=False)


__all__ = ["DeviceToolJob", "DeviceToolJobArchive", "tool_job_pk"]
