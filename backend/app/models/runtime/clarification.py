from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"
    __table_args__ = (
        Index("ix_clarification_questions_session_status", "session_id", "status"),
        Index("ix_clarification_questions_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    run_id = Column(String(36), nullable=True)

    question_id = Column(String(100), nullable=False)
    question_text = Column(Text, nullable=False)
    context_json = Column(JSON, nullable=False, default=dict)

    status = Column(String(30), nullable=False, default="open", index=True)
    priority = Column(String(20), nullable=False, default="medium")

    answer_text = Column(Text, nullable=True)
    answered_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    answered_at = Column(DateTime, nullable=True)
    skipped_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    skipped_at = Column(DateTime, nullable=True)

    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    session = relationship("Session")
    project = relationship("Project")
    requester = relationship("User", foreign_keys=[requested_by])
    answerer = relationship("User", foreign_keys=[answered_by])
    skipper = relationship("User", foreign_keys=[skipped_by])
