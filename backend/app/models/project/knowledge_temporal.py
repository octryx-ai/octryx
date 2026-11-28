"""Provenance of the Workspace knowledge graph: the evidence span each extraction episode came from."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


class KnowledgeGraphEpisode(WorkspaceBound, Base):
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


class KnowledgeGraphWorkspace(WorkspaceBound, Base):
    __tablename__ = "knowledge_graph_workspaces"

    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    embedding_space_key = Column(String(60), nullable=False)
    schema_ensured_at = Column(DateTime, nullable=False, default=utc_now)
