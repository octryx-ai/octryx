"""Durable cross-person offers; a planned child is not an executable Run."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now

HANDOFF_STATES = frozenset({"offered", "accepted", "timed_out", "rejected", "owner_lost", "stopped", "child_done"})


class WorkflowHandoff(Base):
    __tablename__ = "workflow_handoffs"
    __table_args__ = (
        CheckConstraint("state IN ('offered','accepted','timed_out','rejected','owner_lost','stopped','child_done')",
                        name="ck_handoff_state"),
        CheckConstraint("target_kind IN ('person','role','group')", name="ck_handoff_target"),
        CheckConstraint("schema_version = 'handoff/v1'", name="ck_handoff_schema"),
        CheckConstraint("state_version >= 1 AND owner_epoch >= 0 AND round >= 1", name="ck_handoff_versions"),
        CheckConstraint("state != 'accepted' OR (accepted_by IS NOT NULL AND accepted_at IS NOT NULL AND "
                        "receiver_session_id IS NOT NULL AND child_run_id IS NOT NULL AND owner_epoch >= 1)",
                        name="ck_handoff_accepted_owner"),
        CheckConstraint("(child_run_id IS NULL AND receiver_session_id IS NULL) OR "
                        "(child_run_id IS NOT NULL AND receiver_session_id IS NOT NULL)", name="ck_handoff_child_pair"),
        Index("ix_handoff_parent_slot", "parent_run_id", "parent_node_id", "parent_entry", unique=True),
        Index("ix_handoff_offers", "workspace_id", "state", "expires_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    parent_node_id = Column(String(128), nullable=False)
    parent_entry = Column(Integer, nullable=False)
    parent_state_version = Column(Integer, nullable=False)
    parent_version_id = Column(String(36), nullable=False)
    child_descriptor = Column(JSON, nullable=False)
    child_run_id = Column(String(36), ForeignKey("workflow_runs.id"), nullable=True, unique=True)
    receiver_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    schema_version = Column(String(24), nullable=False, default="handoff/v1")
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    target_kind = Column(String(12), nullable=False)
    target_key = Column(String(180), nullable=False)
    contract = Column(JSON, nullable=False)
    envelopes = Column(JSON, nullable=False)
    acceptance = Column(Text, nullable=False)
    payload_hash = Column(String(71), nullable=False)
    detach = Column(Boolean, nullable=False, default=False)
    state = Column(String(20), nullable=False, default="offered")
    state_version = Column(Integer, nullable=False, default=1)
    owner_epoch = Column(Integer, nullable=False, default=0)
    round = Column(Integer, nullable=False, default=1)
    deputy_active = Column(Boolean, nullable=False, default=False)
    accepted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    runtime_snapshot = Column(JSON, nullable=False, default=dict)
    child_outcome = Column(JSON, nullable=False, default=dict)
    owner_history = Column(JSON, nullable=False, default=list)
    issued_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class WorkflowHandoffResponse(Base):
    __tablename__ = "workflow_handoff_responses"
    __table_args__ = (
        Index("uq_handoff_personal_response", "handoff_id", "round", "user_id", unique=True),
        CheckConstraint("round >= 1", name="ck_handoff_response_round"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    handoff_id = Column(String(36), ForeignKey("workflow_handoffs.id", ondelete="CASCADE"), nullable=False)
    round = Column(Integer, nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
