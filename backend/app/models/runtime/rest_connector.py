"""Custom REST connector: an API an admin adds without code, its operations, connections and call runs."""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

GLOBAL_CONNECTION_SCOPE = "global"


def uuid_pk() -> str:
    return str(uuid.uuid4())


class RestApiDefinition(Base):
    __tablename__ = "rest_api_definitions"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(24), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    source_kind = Column(String(16), nullable=False, default="manual")
    source_url = Column(Text, nullable=True)
    spec_version = Column(String(16), nullable=True)
    servers = Column(JSON, default=list, nullable=False)
    auth = Column(JSON, default=dict, nullable=False)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    # The OData response preset its operations inherit (collection reads, no own settings); empty: none.
    default_preset = Column(String(24), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class RestApiOperation(Base):
    __tablename__ = "rest_api_operations"
    __table_args__ = (UniqueConstraint("definition_id", "op_key", name="uq_rest_api_operations_key"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    definition_id = Column(String(36), ForeignKey("rest_api_definitions.id"), nullable=False, index=True)
    op_key = Column(String(32), nullable=False)
    method = Column(String(8), nullable=False)
    path = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    parameters = Column(JSON, default=list, nullable=False)
    request_body = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    read_only = Column(Boolean, nullable=False, default=False)
    llm_name = Column(String(32), nullable=True)
    llm_description = Column(Text, nullable=True)
    params_overlay = Column(JSON, default=dict, nullable=False)
    grants = Column(JSON, default=list, nullable=False)
    response_select = Column(JSON, default=list, nullable=False)
    records_path = Column(String(200), nullable=True)
    pagination = Column(JSON, default=dict, nullable=False)
    capability = Column(String(16), nullable=True)
    idempotent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class RestApiConnection(WorkspaceBound, Base):
    __tablename__ = "rest_api_connections"
    __table_args__ = (UniqueConstraint("definition_id", "scope_key", name="uq_rest_api_connections_scope"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    definition_id = Column(String(36), ForeignKey("rest_api_definitions.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    scope_key = Column(String(36), nullable=False)
    name = Column(String(64), nullable=False)
    base_url = Column(Text, nullable=False)
    config = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class RestApiCallRun(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "rest_api_call_runs"
    __table_args__ = (Index("ix_rest_api_call_runs_operation_started", "operation_id", "started_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    definition_id = Column(String(36), nullable=False, index=True)
    operation_id = Column(String(36), nullable=False)
    connection_id = Column(String(36), nullable=True)
    project_id = Column(String(36), nullable=True, index=True)
    actor_user_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(36), nullable=True)
    tool_name = Column(String(80), nullable=False)
    identity = Column(String(16), nullable=False, default="technical")
    status = Column(String(24), nullable=False, default="running", index=True)
    failure_category = Column(String(60), nullable=True)
    error = Column(Text, nullable=True)
    http_status = Column(Integer, nullable=True)
    scope_json = Column(JSON, default=dict, nullable=False)
    arguments_json = Column(JSON, default=dict, nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    dropped_count = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    approval_id = Column(String(36), nullable=True)
    write_plan_id = Column(String(40), nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
