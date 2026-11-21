import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class RuntimeContextCompaction(Base):
    __tablename__ = "runtime_context_compactions"
    __table_args__ = (
        Index("ix_runtime_context_compactions_session_status", "session_id", "status"),
        Index("ix_runtime_context_compactions_session_index", "session_id", "compaction_index"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="active", index=True)
    compaction_index = Column(Integer, nullable=False, default=1)
    source_first_message_id = Column(String(36), nullable=True, index=True)
    source_last_message_id = Column(String(36), nullable=True, index=True)
    source_message_count = Column(Integer, nullable=False, default=0)
    recent_message_count = Column(Integer, nullable=False, default=0)
    summary_text = Column(Text, nullable=False, default="")
    evidence_refs_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    superseded_at = Column(DateTime, nullable=True, index=True)
