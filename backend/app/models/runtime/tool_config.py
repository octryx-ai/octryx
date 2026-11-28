import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class BuiltInToolConfig(WorkspaceBound, Base):
    __tablename__ = "built_in_tool_configs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    tool_name = Column(String(200), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    description = Column(Text, nullable=True)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")
