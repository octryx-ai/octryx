"""Named connections: several credential units per connector and scope, each bound to source scopes.

A named connection is one more account of a connector (``confluence``, ``jira``, ``servicenow``) in one
scope: a Workspace (``project_id``) or the global scope (``project_id`` NULL, ``scope_key`` ``global``).
``config`` holds the connection unit's non-secret fields (URL, auth mode, principal, OIDC options) and
the ``*_secret_ref`` of each secret; a secret value is never stored here. ``bound_scopes`` are the
upper-cased Confluence space keys, Jira project keys or ServiceNow tables this account serves.

``scope_key`` repeats the scope as a non-null value so the name is unique per connector and scope in
the database, the global scope included (a NULL ``project_id`` would never collide in a unique index).
The name is unique case-insensitively (``uq_connector_named_connections_name_ci`` on ``lower(name)``), so
"Client-A" and "client-a" can never both exist; ``id`` is the stable, server-generated reference.

``last_test`` is the outcome of the last test of the *saved* connection (``ok``, ``at``, the fixed
summary), never of a test with typed values and never a secret.

The row is also the platform's **connection**: ``available_in``
(``all`` | ``selected``, the Workspaces in ``connection_workspaces``), ``owner_kind`` (``platform`` |
``workspace``) with ``owner_workspace_id``, ``is_active``, the last known ``state`` (``ok`` | ``failing`` |
``untested``; ``disabled`` is ``is_active`` false), ``state_reason``, ``last_tested_at`` and
``agent_tools_level`` (``off`` | ``read`` | ``write``).
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now

GLOBAL_SCOPE_KEY = "global"


def uuid_pk():
    return str(uuid.uuid4())


def _default_available_in(context) -> str:
    return "selected" if context.get_current_parameters().get("project_id") else "all"


class ConnectorNamedConnection(Base):
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
