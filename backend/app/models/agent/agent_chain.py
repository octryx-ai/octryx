import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class AgentChainTemplate(WorkspaceBound, Base):
    __tablename__ = "agent_chain_templates"
    __table_args__ = (
        Index("ix_agent_chain_templates_project_active", "project_id", "is_active"),
        Index("ix_agent_chain_templates_name_project", "name", "project_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    steps_json = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)


class AgentChainRun(WorkspaceBound, Base):
    __tablename__ = "agent_chain_runs"
    __table_args__ = (
        Index("ix_agent_chain_runs_template_started", "template_id", "started_at"),
        Index("ix_agent_chain_runs_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    template_id = Column(String(36), ForeignKey("agent_chain_templates.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    started_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    input_payload = Column(JSON, nullable=False, default=dict)
    output_payload = Column(JSON, nullable=False, default=dict)
    step_results = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
