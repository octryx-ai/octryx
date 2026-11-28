"""A device job without an agent: pinned tools run on code the platform sent (``services/devices/tool_jobs``).
``pending`` until a candidate's channel tick claims it (``sent``), then ``done``, ``timeout`` or ``failed``."""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def tool_job_pk() -> str:
    return f"tj_{secrets.token_hex(10)}"


class DeviceToolJob(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
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


class DeviceToolJobArchive(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"job_id": "device_tool_jobs"}
    __tablename__ = "device_tool_job_archives"

    id = Column(String(40), primary_key=True, default=lambda: f"ta_{secrets.token_hex(10)}")
    job_id = Column(String(40), ForeignKey("device_tool_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    data = Column(LargeBinary, nullable=False)


__all__ = ["DeviceToolJob", "DeviceToolJobArchive", "tool_job_pk"]
