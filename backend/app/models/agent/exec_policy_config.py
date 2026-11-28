from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...db import Base
from ...db.workspace_bound import WorkspaceBound


class ExecPolicyConfig(WorkspaceBound, Base):
    __tablename__ = "exec_policy_configs"

    id = Column(String(36), primary_key=True)
    name = Column(String(120), nullable=False, default="default")
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    config_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project")
