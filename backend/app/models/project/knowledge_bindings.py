"""Explicit, one-directional read bindings between Knowledge Workspaces of one Instance."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

BINDING_STATE_ACTIVE = "active"
BINDING_STATE_REVOKED = "revoked"


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeWorkspaceBinding(WorkspaceBound, Base):
    __workspace_column__ = "reader_project_id"
    __also_workspace_columns__ = ("source_project_id",)
    __tablename__ = "knowledge_workspace_bindings"
    __table_args__ = (
        UniqueConstraint("reader_project_id", "source_project_id", name="uq_knowledge_workspace_bindings_pair"),
        Index("ix_knowledge_workspace_bindings_reader", "reader_project_id", "state"),
        Index("ix_knowledge_workspace_bindings_source", "source_project_id", "state"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    reader_project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    products = Column(JSON, nullable=False, default=list)
    state = Column(String(20), nullable=False, default=BINDING_STATE_ACTIVE)
    reason = Column(Text, nullable=False, default="")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    revoked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)


__all__ = ["BINDING_STATE_ACTIVE", "BINDING_STATE_REVOKED", "KnowledgeWorkspaceBinding"]
