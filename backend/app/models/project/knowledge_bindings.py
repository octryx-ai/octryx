"""Explicit read bindings between Knowledge Workspaces of one Instance.

A binding lets one Workspace (the reader) read another Workspace's Knowledge (the source), without
copying it: a special-project Workspace reads the Instance's main brain, or every project Workspace
reads a shared library Workspace holding the Spring Boot or shipping protocol packages. It is:

- **explicit and one-directional**: the reader reads the source, never the other way round;
- **non-transitive**: the source's own bindings are not followed;
- **product-bounded**: ``products`` limits the read to those product facets; empty means all;
- **consented by both sides**: created by someone who authors in both Workspaces;
- **revocable by either side**: a revoked binding stays as a record with who revoked it and when.

The source's data classification must not exceed the reader's, checked when the binding is created
and again on every read (``services/knowledge/access/bindings.py``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now

BINDING_STATE_ACTIVE = "active"
BINDING_STATE_REVOKED = "revoked"


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeWorkspaceBinding(Base):
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
