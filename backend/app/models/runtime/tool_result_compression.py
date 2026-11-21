import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ToolResultCompressor(Base):
    __tablename__ = "tool_result_compressors"
    __table_args__ = (Index("ix_tool_result_compressors_tool_active", "tool_name", "is_active"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    tool_name = Column(String(120), nullable=False, index=True, unique=True)
    strategy = Column(String(80), nullable=False)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class ToolResultCompressionLog(Base):
    __tablename__ = "tool_result_compression_log"
    __table_args__ = (Index("ix_tool_result_compression_log_session_tool", "session_id", "tool_name"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    tool_name = Column(String(120), nullable=False, index=True)
    compressor_id = Column(String(36), ForeignKey("tool_result_compressors.id"), nullable=True, index=True)
    strategy = Column(String(80), nullable=False)
    original_tokens = Column(Integer, nullable=False, default=0)
    compressed_tokens = Column(Integer, nullable=False, default=0)
    compression_ratio = Column(Integer, nullable=False, default=0)
    request_id = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
