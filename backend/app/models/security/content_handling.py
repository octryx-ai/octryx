"""Content handling: a Workspace's chosen action per sensitive content kind and its governance alias
(``content_security.handling``).

- :class:`WorkspaceContentHandling` — one row per Workspace and kind, only where the Workspace admin chose an action;
  no row means the shipped default of each enforcement surface.
- :class:`WorkspaceContentGovernance` — at most one row per Workspace: the governed model alias every ``reroute`` /
  ``mask_reroute`` kind of the Workspace is sent to (no row: no alias, and no kind may reroute).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkspaceContentHandling(Base):
    __tablename__ = "workspace_content_handling"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", name="uq_workspace_content_handling"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(40), nullable=False)
    action = Column(String(20), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class WorkspaceContentGovernance(Base):
    __tablename__ = "workspace_content_governance"

    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    governance_alias = Column(String(120), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["WorkspaceContentGovernance", "WorkspaceContentHandling"]
