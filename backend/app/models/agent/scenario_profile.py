import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class ScenarioProfile(Base):
    __tablename__ = "scenario_profiles"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    priority = Column(Integer, default=100, nullable=False)
    match_config = Column(JSON, default=dict)
    planner_config = Column(JSON, default=dict)
    execution_config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    owner = relationship("User")
    project = relationship("Project")
