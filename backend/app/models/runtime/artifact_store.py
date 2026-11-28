import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ToolArtifact(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "tool_artifacts"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    tool_name = Column(String(200), nullable=False, index=True)
    storage_backend = Column(String(40), nullable=False, default="disk_json_gzip")
    relative_path = Column(String(500), nullable=False, unique=True)
    content_sha256 = Column(String(64), nullable=False)
    payload_size_bytes = Column(Integer, nullable=False, default=0)
    is_compressed = Column(Boolean, nullable=False, default=True)
    preview_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)

    session = relationship("Session")
