"""Named connections: several credential units per connector and scope, each bound to source scopes."""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

GLOBAL_SCOPE_KEY = "global"


def uuid_pk():
    return str(uuid.uuid4())


def _default_available_in(context) -> str:
    return "selected" if context.get_current_parameters().get("project_id") else "all"


class ConnectorNamedConnection(WorkspaceBound, Base):
    __tablename__ = "connector_named_connections"
    __table_args__ = (
        UniqueConstraint("tool_name", "scope_key", "name", name="uq_connector_named_connections_name"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    tool_name = Column(String(40), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    scope_key = Column(String(36), nullable=False)
    name = Column(String(64), nullable=False)
    config = Column(JSON, default=dict, nullable=False)
    bound_scopes = Column(JSON, default=list, nullable=False)
    last_test = Column(JSON, nullable=True)
    # A Workspace row (``project_id``) is available in that Workspace only unless set otherwise.
    available_in = Column(String(16), nullable=False, default=_default_available_in, server_default="all")
    owner_kind = Column(String(16), nullable=False, default="platform", server_default="platform")
    owner_workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())
    state = Column(String(16), nullable=False, default="untested", server_default="untested")
    state_reason = Column(Text, nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    agent_tools_level = Column(String(8), nullable=False, default="read", server_default="read")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", foreign_keys=[project_id])


Index(
    "uq_connector_named_connections_name_ci",
    ConnectorNamedConnection.tool_name,
    ConnectorNamedConnection.scope_key,
    func.lower(ConnectorNamedConnection.name),
    unique=True,
)
