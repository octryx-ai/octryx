"""Where a connection is available and how a Workspace narrows it."""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class ConnectionWorkspace(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
    __tablename__ = "connection_workspaces"
    __table_args__ = (Index("ix_connection_workspaces_workspace_id", "workspace_id"),)

    connection_id = Column(
        String(36), ForeignKey("connector_named_connections.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)


class ConnectionDeviation(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
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
