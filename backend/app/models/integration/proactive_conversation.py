"""Model for tracking proactive Teams conversations bound to Jira tickets."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid_pk() -> str:
    return str(uuid.uuid4())


class ProactiveConversation(WorkspaceBound, Base):
    __tablename__ = "proactive_conversations"
    __table_args__ = (
        Index("ix_proactive_conv_conversation", "conversation_id"),
        Index("ix_proactive_conv_ticket", "ticket_id"),
        Index("ix_proactive_conv_session", "session_id"),
        Index("ix_proactive_conv_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    channel_config_id = Column(String(36), nullable=True, index=True)

    ticket_id = Column(String(60), nullable=False)  # e.g. "PROJ-123"
    reporter_email = Column(String(320), nullable=False)

    teams_user_id = Column(String(200), nullable=False)
    conversation_id = Column(String(500), nullable=False)
    service_url = Column(String(500), nullable=False)
    target = Column(String(700), nullable=False)  # "serviceUrl|conversationId"

    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)

    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pending")  # pending | answered | expired | cancelled

    created_at = Column(DateTime, default=utc_now, index=True)
    answered_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    project = relationship("Project")
