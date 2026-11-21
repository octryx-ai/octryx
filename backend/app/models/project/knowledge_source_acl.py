"""Source ACL facets mirrored from the source systems, and their projection marker.

A source without an ACL row is readable by every member of its Workspace. A
source *with* a row is restricted: only the principals listed for it may read it, and a row with no
principals is readable by nobody. The ACL belongs to the **source**, keyed by its Workspace-stable
``source_key``, not to one revision: a restriction that changes without a content change must take
effect at once, and it also covers the source's history. Keying by ``source_key`` lets a connector
write the ACL *before* the first revision exists, so no revision of a restricted item is ever
committed, projected or cited as if it were public.

- ``KnowledgeSourceAcl``: one restricted source: the restriction mechanism and, for explanation
  only, the bounded source-system principal labels and how many expanded identities it admits.
- ``KnowledgeSourceAclPrincipal``: the principal keys (``access/acl_keys.py``) the source admits.
  A key is a one-way hash of a normalized email address, never the address itself.
- ``KnowledgeWorkspaceAclMarker``: the Workspace's indexed spans all carry their ACL marker
  (``projection/acl_marker.py``); retrieval refuses a Workspace without it (never projected) with
  an explicit state instead of an empty answer.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


class KnowledgeSourceAcl(Base):
    __tablename__ = "knowledge_source_acls"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_key = Column(String(200), primary_key=True)
    restriction = Column(String(40), nullable=False)
    # Explanation only: the source system's own principal labels (bounded) and the mapping counts.
    source_principals = Column(JSON, nullable=False, default=list)
    principal_count = Column(Integer, nullable=False, default=0)
    matched_user_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeSourceAclPrincipal(Base):
    __tablename__ = "knowledge_source_acl_principals"
    __table_args__ = (Index("ix_knowledge_source_acl_principals_key", "project_id", "principal_key"),)

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_key = Column(String(200), primary_key=True)
    principal_key = Column(String(64), primary_key=True)


class KnowledgeWorkspaceAclMarker(Base):
    __tablename__ = "knowledge_workspace_acl_markers"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    marker_version = Column(Integer, nullable=False, default=1)
    converged_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["KnowledgeSourceAcl", "KnowledgeSourceAclPrincipal", "KnowledgeWorkspaceAclMarker"]
