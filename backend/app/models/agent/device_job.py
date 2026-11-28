"""A chat thread's work on one of its owner's devices, its events and its tool approvals."""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def job_pk() -> str:
    return f"dj_{secrets.token_hex(8)}"


def approval_pk() -> str:
    return f"da_{secrets.token_hex(8)}"


class DeviceJob(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions"}
    __workspace_column__ = "workspace_id"
    __tablename__ = "device_jobs"
    __table_args__ = (Index("ix_device_jobs_device_status", "device_id", "status"),)

    id = Column(String(40), primary_key=True, default=job_pk)
    # Empty while a chat turn waits for a free server runner (``waiting_runner``).
    device_id = Column(String(40), ForeignKey("user_devices.id"), nullable=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    folder = Column(String(500), nullable=False)
    profile = Column(String(20), nullable=False)
    # (waiting_runner →) offered → running → idle (turn done) … ; terminal: rejected, failed, device_lost, closed
    status = Column(String(20), nullable=False, default="offered", index=True)
    status_reason = Column(String(80), nullable=True)
    policy_decision_id = Column(String(80), nullable=True)
    # The coding engine the job's session runs on (``agent_gateway/engine_keys``), fixed at its first offer: a
    # Claude Code session cannot be continued by Codex or the other way round. Empty until that first offer
    # (``services/devices/job_engine``); read as Claude Code.
    engine = Column(String(20), nullable=True)
    claude_session_id = Column(String(80), nullable=True)
    resume_claude_session_id = Column(String(80), nullable=True)
    # The current turn: its prompt and whether the device has it (pending → sent → accepted).
    turn_id = Column(String(40), nullable=True)
    turn_prompt = Column(Text, nullable=True)
    turn_state = Column(String(20), nullable=True)
    turn_count = Column(Integer, nullable=False, default=0)
    # The model the chat asked for this turn (empty: the device's default) and the one the device reported.
    turn_model = Column(String(200), nullable=True)
    model = Column(String(200), nullable=True)
    # The turn's Claude Code permission mode and effort, chosen in the chat (empty: defaults).
    turn_permission_mode = Column(String(20), nullable=True)
    turn_effort = Column(String(10), nullable=True)
    # Stop: requested by the owner, then sent to the device.
    stop_state = Column(String(20), nullable=True)
    last_event_seq = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(12, 6), nullable=True)
    usage = Column(JSON, nullable=True)
    disconnected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    finished_at = Column(DateTime, nullable=True)


class DeviceJobEvent(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"job_id": "device_jobs"}
    __tablename__ = "device_job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_device_job_events_seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(40), ForeignKey("device_jobs.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    type = Column(String(40), nullable=False)
    body = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class DeviceJobApproval(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"job_id": "device_jobs"}
    __tablename__ = "device_job_approvals"
    # A person's pending approvals, newest first: read by every attention and inbox poll.
    __table_args__ = (Index("ix_device_job_approvals_owner_status_created", "owner_user_id", "status", "created_at"),)

    id = Column(String(40), primary_key=True, default=approval_pk)
    # The device's own id for the request (unique per job), echoed back with the decision.
    request_id = Column(String(64), nullable=False)
    job_id = Column(String(40), ForeignKey("device_jobs.id"), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    tool = Column(String(120), nullable=False)
    input_preview = Column(Text, nullable=True)
    input_digest = Column(String(40), nullable=True)
    can_allow_job_edits = Column(Integer, nullable=False, default=0)
    # pending → allowed | allowed_job_edits | denied | expired
    status = Column(String(30), nullable=False, default="pending", index=True)
    decided_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    decision_state = Column(String(20), nullable=True)  # pending → sent (to the device)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    decided_at = Column(DateTime, nullable=True)


__all__ = ["DeviceJob", "DeviceJobApproval", "DeviceJobEvent", "approval_pk", "job_pk"]
