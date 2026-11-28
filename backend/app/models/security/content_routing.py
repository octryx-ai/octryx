"""Content routing: the sensitive categories a conversation already contained."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class ContentConversationState(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "content_conversation_state"
    __table_args__ = (
        UniqueConstraint("session_id", "conversation_key", name="uq_content_conversation_state"),
        Index("ix_content_conversation_state_session", "session_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    conversation_key = Column(String(100), nullable=False)
    categories = Column(JSON, nullable=False, default=list)
    detectors = Column(JSON, nullable=False, default=dict)
    policy_id = Column(String(120), nullable=True)
    decision_id = Column(String(36), nullable=True)
    route_to = Column(String(120), nullable=True)
    first_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["ContentConversationState"]
