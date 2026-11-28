"""Structured handoffs and takeovers of Work Items (agent coordination board)."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


class WorkItemHandoff(WorkspaceBound, Base):
    __tablename__ = "work_item_handoff"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_work_item_handoff_version"),
        Index("ix_work_item_handoff_project", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    author_kind = Column(String(10), nullable=False)  # agent | human
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    author_agent_hash = Column(String(24), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    sections = Column(JSON, nullable=False, default=dict)


class WorkItemTakeover(WorkspaceBound, Base):
    __tablename__ = "work_item_takeover"
    __table_args__ = (
        Index(
            "uq_work_item_takeover_pending",
            "work_item_id",
            "requester_ref",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_work_item_takeover_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    # The claim being taken over, and its holder at request time (null when the item was unclaimed).
    from_claim_id = Column(String(36), ForeignKey("work_item_claim.id", ondelete="SET NULL"), nullable=True)
    from_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    from_agent_hash = Column(String(24), nullable=True)
    to_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_agent_hash = Column(String(24), nullable=True)
    to_agent_kind = Column(String(20), nullable=True)  # gateway_session | mcp_session
    requester_ref = Column(String(64), nullable=False)  # the agent hash, or "user:<id>" for an admin request
    reason = Column(Text, nullable=True)
    automatic = Column(Boolean, nullable=False, default=False)
    message_id = Column(String(36), ForeignKey("agent_board_message.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(12), nullable=False, default="pending")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    new_claim_id = Column(String(36), ForeignKey("work_item_claim.id", ondelete="SET NULL"), nullable=True)
    # Who decided (``human`` | ``system``), the Workspace handoff mode at request time, and the policy the server
    # applied when it confirmed by itself.
    decided_by_kind = Column(String(10), nullable=True)
    policy_mode = Column(String(10), nullable=True)
    policy_snapshot = Column(JSON, nullable=True)


class WorkItemHandoffAttachment(WorkspaceBound, Base):
    """A handoff's git bundle: stored in the object store as up to four content-addressed parts."""

    __tablename__ = "work_item_handoff_attachment"
    __table_args__ = (Index("ix_work_item_handoff_attachment_item", "work_item_id", "created_at"),)

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    uploaded_by = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False, default="git_bundle")
    byte_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    parts = Column(JSON, nullable=False, default=list)  # [{bucket, key, version_id, content_sha256, size}]
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["WorkItemHandoff", "WorkItemHandoffAttachment", "WorkItemTakeover"]
