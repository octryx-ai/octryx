"""The deterministic structured knowledge graph of a Workspace.

Rule-based extractors (``services/knowledge/structured``) turn manual spans, configuration files and
operations records into typed nodes and edges without any model call. Every row records the
extraction profile it was made under (``structured-v4``) and where it is cited from, so the graph
is served only through the reader's own citation resolution (``ledger/citations.resolve_citations``).

- ``KnowledgeStructuredNode``: one node as one source revision states it. The same entity stated
  by several revisions (an assignment group, a mentioned Jira key) shares ``node_id``, the digest
  of its type and key, and is one node in every read.
- ``KnowledgeStructuredEdge``: one typed edge between two node ids. ``revision_id`` is the revision
  it was extracted from, or ``NULL`` for a linkage edge computed across sources (a setting that
  configures a documented parameter). ``citations`` lists every span it rests on.
- ``KnowledgeStructuredExtraction``: the ledger of extracted revisions, so a rebuild skips a
  revision already extracted under the current profile and retires one that is no longer current.
- ``KnowledgeStructuredBuild``: an admin or source-sync request to build layers, run by the
  projection worker in bounded slices, and its run report.
- ``KnowledgeStructuredProfile``: the saved revisions of a Workspace's own extraction profile.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeStructuredNode(Base):
    __tablename__ = "knowledge_structured_nodes"
    __table_args__ = (
        UniqueConstraint("revision_id", "profile", "node_type", "node_key", name="uq_knowledge_structured_nodes_key"),
        Index("ix_knowledge_structured_nodes_node", "project_id", "node_id"),
        Index("ix_knowledge_structured_nodes_type", "project_id", "layer", "node_type"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), nullable=False)
    profile = Column(String(40), nullable=False)
    layer = Column(String(20), nullable=False)
    node_type = Column(String(40), nullable=False)
    node_key = Column(String(512), nullable=False)
    node_id = Column(String(64), nullable=False)
    label = Column(String(300), nullable=False)
    properties = Column(JSON, nullable=False, default=dict)
    # Where the revision states the node: a span, and for a file a 1-based line inside it.
    span_ordinal = Column(Integer, nullable=True)
    line = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeStructuredEdge(Base):
    __tablename__ = "knowledge_structured_edges"
    __table_args__ = (
        UniqueConstraint("project_id", "edge_key", name="uq_knowledge_structured_edges_key"),
        Index("ix_knowledge_structured_edges_source", "project_id", "source_id"),
        Index("ix_knowledge_structured_edges_target", "project_id", "target_id"),
        Index("ix_knowledge_structured_edges_revision", "revision_id"),
        Index("ix_knowledge_structured_edges_type", "project_id", "layer", "edge_type"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), nullable=True)
    profile = Column(String(40), nullable=False)
    layer = Column(String(20), nullable=False)
    edge_type = Column(String(40), nullable=False)
    edge_key = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False)
    target_id = Column(String(64), nullable=False)
    properties = Column(JSON, nullable=False, default=dict)
    # [[revision_id, span_ordinal, line or null], ...]: every span the edge rests on.
    citations = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeStructuredExtraction(Base):
    __tablename__ = "knowledge_structured_extractions"
    __table_args__ = (Index("ix_knowledge_structured_extractions_workspace", "project_id", "layer"),)

    revision_id = Column(
        String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    profile = Column(String(40), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    layer = Column(String(20), nullable=False)
    extractor = Column(String(40), nullable=False)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    # Fixed warning tokens with counts (``{"table_header_ambiguous": 2}``); never source text.
    warnings = Column(JSON, nullable=False, default=dict)
    extracted_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeStructuredBuild(Base):
    __tablename__ = "knowledge_structured_builds"
    __table_args__ = (
        Index("ix_knowledge_structured_builds_workspace", "project_id", "requested_at"),
        Index("ix_knowledge_structured_builds_due", "state", "lease_until"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    profile = Column(String(40), nullable=False)
    layers = Column(JSON, nullable=False, default=list)
    # ``manual`` (an author asked) or ``source_sync`` (a completed sync refreshed it).
    trigger = Column(String(20), nullable=False)
    # pending -> running -> completed | failed
    state = Column(String(20), nullable=False)
    requested_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at = Column(DateTime, nullable=False, default=utc_now)
    claimed_by = Column(String(120), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    failure = Column(String(60), nullable=True)
    report = Column(JSON, nullable=False, default=dict)


class KnowledgeStructuredProfile(Base):
    """One saved revision of a Workspace's own structured profile; the highest revision is in force.

    ``document`` is a full profile document (the schema of ``profiles/structured-v<n>.json``), or
    ``NULL`` when the revision returned the Workspace to the instance default. ``profile_id`` is the
    id its rows are written under (``structured-v4-w3``).
    """

    __tablename__ = "knowledge_structured_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_knowledge_structured_profiles_revision"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    revision = Column(Integer, nullable=False)
    profile_id = Column(String(40), nullable=True)
    document = Column(JSON, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
