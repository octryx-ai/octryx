import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class PrefetchCacheEntry(Base):
    __tablename__ = "prefetch_cache"
    __table_args__ = (Index("ix_prefetch_cache_lookup", "session_id", "tool_name", "params_hash"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False, index=True)
    params_hash = Column(String(64), nullable=False, index=True)
    params_json = Column(JSON, default=dict)
    result_json = Column(JSON, default=dict)
    status = Column(String(20), nullable=False, default="completed", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
