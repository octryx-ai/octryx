import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class DatabaseConnector(WorkspaceBound, Base):
    __tablename__ = "database_connectors"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    db_type = Column(String(40), nullable=False, default="postgresql", index=True)
    connection_config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    project = relationship("Project")
    query_tools = relationship(
        "DatabaseQueryTool",
        back_populates="connector",
        cascade="all, delete-orphan",
        order_by="DatabaseQueryTool.tool_name.asc()",
    )


class DatabaseQueryTool(WorkspaceBound, Base):
    __tablename__ = "database_query_tools"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    connector_id = Column(String(36), ForeignKey("database_connectors.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    tool_name = Column(String(200), nullable=False, unique=True, index=True)
    display_name = Column(String(200), nullable=True)
    description = Column(Text, nullable=False, default="")
    sql_template = Column(Text, nullable=False)
    parameters_schema = Column(JSON, default=dict)
    row_level_security_rules = Column(JSON, default=list)
    allowed_roles = Column(JSON, default=list)
    max_rows = Column(Integer, nullable=False, default=100)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    connector = relationship("DatabaseConnector", back_populates="query_tools")
    project = relationship("Project")


class DatabaseQueryToolRun(WorkspaceBound, Base):
    __workspace_owners__ = {"query_tool_id": "database_query_tools", "session_id": "sessions"}
    __tablename__ = "database_query_tool_runs"
    __table_args__ = (
        Index("ix_database_query_tool_runs_tool_started", "query_tool_id", "started_at"),
        Index("ix_database_query_tool_runs_connector_status", "connector_id", "status"),
        Index("ix_database_query_tool_runs_project_started", "project_id", "started_at"),
        Index("ix_database_query_tool_runs_session_started", "session_id", "started_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    query_tool_id = Column(String(36), ForeignKey("database_query_tools.id"), nullable=False, index=True)
    connector_id = Column(String(36), ForeignKey("database_connectors.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    tool_name = Column(String(200), nullable=False, index=True)
    connector_name = Column(String(160), nullable=False)
    db_type = Column(String(40), nullable=False)
    status = Column(String(40), nullable=False, default="running", index=True)
    failure_category = Column(String(80), nullable=True, index=True)
    retryable = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    duration_ms = Column(Integer, nullable=True)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    row_count = Column(Integer, nullable=False, default=0)
    max_rows = Column(Integer, nullable=False, default=0)
    applied_rls_rules = Column(JSON, default=list, nullable=False)
    parameters_json = Column(JSON, default=dict, nullable=False)
    evidence_json = Column(JSON, default=dict, nullable=False)

    query_tool = relationship("DatabaseQueryTool")
    connector = relationship("DatabaseConnector")
    project = relationship("Project")
    actor = relationship("User")


