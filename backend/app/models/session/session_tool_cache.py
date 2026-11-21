import uuid

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class SessionToolCacheEntry(Base):
    __tablename__ = "session_tool_cache"
    __table_args__ = (Index("ix_session_tool_cache_lookup", "session_id", "tool_name", "params_hash"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), nullable=False, index=True)
    tool_name = Column(String(120), nullable=False, index=True)
    params_hash = Column(String(64), nullable=False, index=True)
    result_json = Column(JSON, nullable=False, default=dict)
    cached_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    ttl_seconds = Column(Integer, nullable=False, default=0)
    hit_count = Column(Integer, nullable=False, default=0)
