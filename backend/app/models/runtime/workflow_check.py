"""The result of a workflow's checks for one turn.

Written at turn end in platform chat (``services/workflow_checks``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class WorkflowCheckResult(Base):
    __tablename__ = "workflow_check_results"
    __table_args__ = (
        Index("ix_workflow_check_results_session", "session_id", "created_at"),
        Index("ix_workflow_check_results_workflow", "workflow_key", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    trace_id = Column(String(80), nullable=True)
    workflow_key = Column(String(180), nullable=False)
    workflow_version = Column(Integer, nullable=True)
    # chat
    runtime = Column(String(20), nullable=False)
    # passed | not_verified
    state = Column(String(20), nullable=False)
    results_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
