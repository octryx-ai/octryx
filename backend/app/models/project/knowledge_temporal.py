"""PostgreSQL provenance of the Workspace knowledge graph.

The graph's entities and facts live in ``kg_node``/``kg_edge`` and stay rebuildable. What makes a
graph fact citable lives here: every extraction episode is exactly one evidence span of one source
revision, and ``KnowledgeGraphEpisode`` records which. A fact names the episodes it was
extracted from, so it resolves through this table to its span, revision, source and origin link;
a fact whose episodes are not here is not served.

``KnowledgeGraphWorkspace`` records in which embedding space the Workspace graph's vectors were
written, because vectors are compared within one space only: a graph built in one space is not
searched with another.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


class KnowledgeGraphEpisode(Base):
    __tablename__ = "knowledge_graph_episodes"
    __table_args__ = (
        Index("ix_knowledge_graph_episodes_workspace", "project_id"),
        Index("ix_knowledge_graph_episodes_revision", "revision_id", "span_ordinal", unique=True),
    )

    episode_uuid = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), nullable=False)
    span_ordinal = Column(Integer, nullable=False)
    group_id = Column(String(60), nullable=False)
    # How the span was extracted (``temporal/change_types.py``); another profile means re-extraction.
    extraction_profile = Column(String(40), nullable=False)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    extracted_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeGraphWorkspace(Base):
    __tablename__ = "knowledge_graph_workspaces"

    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    embedding_space_key = Column(String(60), nullable=False)
    schema_ensured_at = Column(DateTime, nullable=False, default=utc_now)
