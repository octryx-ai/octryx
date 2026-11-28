"""Source ACL facets mirrored from the source systems, and their projection marker."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


class KnowledgeSourceAcl(WorkspaceBound, Base):
    __tablename__ = "knowledge_source_acls"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_key = Column(String(200), primary_key=True)
    restriction = Column(String(40), nullable=False)
    # Explanation only: the source system's own principal labels (bounded) and the mapping counts.
    source_principals = Column(JSON, nullable=False, default=list)
    principal_count = Column(Integer, nullable=False, default=0)
    matched_user_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeSourceAclPrincipal(WorkspaceBound, Base):
    __tablename__ = "knowledge_source_acl_principals"
    __table_args__ = (Index("ix_knowledge_source_acl_principals_key", "project_id", "principal_key"),)

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_key = Column(String(200), primary_key=True)
    principal_key = Column(String(64), primary_key=True)


class KnowledgeWorkspaceAclMarker(WorkspaceBound, Base):
    __tablename__ = "knowledge_workspace_acl_markers"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    marker_version = Column(Integer, nullable=False, default=1)
    converged_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["KnowledgeSourceAcl", "KnowledgeSourceAclPrincipal", "KnowledgeWorkspaceAclMarker"]
