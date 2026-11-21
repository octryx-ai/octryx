import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class SubAgentGroup(Base):
    __tablename__ = "sub_agent_groups"
    __table_args__ = (
        Index("ix_sub_agent_groups_parent_status", "parent_session_id", "status"),
        Index("ix_sub_agent_groups_timeout_at", "timeout_at"),
        Index("ix_sub_agent_groups_created_at", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    parent_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    total_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    child_session_ids_json = Column(JSON, nullable=False, default=list)
    child_statuses_json = Column(JSON, nullable=False, default=dict)
    resume_prompt = Column(Text, nullable=True)
    timeout_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    resumed_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)
