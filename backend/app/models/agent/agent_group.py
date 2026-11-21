import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class AgentGroup(Base):
    __tablename__ = "agent_groups"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(120), nullable=False, index=True)
    description = Column(Text, default="")
    category = Column(String(80), default="general")
    position = Column(Integer, default=100)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    owner = relationship("User")
    project = relationship("Project")
    agents = relationship("AgentDefinition", back_populates="group")
