"""Where a connection is available and how a Workspace narrows it.

- ``ConnectionWorkspace``: one row per Workspace a connection with ``available_in = selected`` serves.
- ``ConnectionDeviation``: a Workspace's deviation from the connection, only ever narrower
  (``services/config_effective``); ``fields`` is the nested deviation (``{"knowledge": {"scope": ...}}``).

Both cascade with the connection and the Workspace; neither holds a secret.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class ConnectionWorkspace(Base):
    __tablename__ = "connection_workspaces"
    __table_args__ = (Index("ix_connection_workspaces_workspace_id", "workspace_id"),)

    connection_id = Column(
        String(36), ForeignKey("connector_named_connections.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)


class ConnectionDeviation(Base):
    __tablename__ = "connection_deviations"
    __table_args__ = (
        UniqueConstraint("connection_id", "workspace_id", name="uq_connection_deviations_connection_workspace"),
        Index("ix_connection_deviations_workspace_id", "workspace_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    connection_id = Column(
        String(36), ForeignKey("connector_named_connections.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    fields = Column(JSON, nullable=False, default=dict)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = ["ConnectionDeviation", "ConnectionWorkspace"]
