"""Content routing: the sensitive categories a conversation already contained.

One row per conversation: the gateway or chat session and the client's conversation id (Claude Code's
``x-claude-code-session-id``; a new id after ``/clear`` is a new conversation, a new chat is a new session). It
feeds ``principal.sensitive`` (a routed conversation stays on the approved model) and the Agents badge. It holds
categories, detector counts, the first time and the policy and decision that first applied — never content.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class ContentConversationState(Base):
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
