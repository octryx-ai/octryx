"""General knowledge-graph tables (tier 2): typed entities, relations, aliases, and version-temporal claims."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeGraphNode(WorkspaceBound, Base):
    __tablename__ = "knowledge_graph_nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "node_type", "node_key", name="uq_knowledge_graph_nodes_type_key"),
        Index("ix_knowledge_graph_nodes_project", "project_id"),
        Index("ix_knowledge_graph_nodes_type", "node_type"),
        Index("ix_knowledge_graph_nodes_embedding_updated_at", "embedding_updated_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    # Nullable project_id == instance-global entity (e.g. a person, a product).
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    node_type = Column(String(60), nullable=False)
    node_key = Column(String(300), nullable=False)
    display_name = Column(String(500), nullable=False, default="")
    description = Column(Text, default="")
    status = Column(String(40), nullable=False, default="active", index=True)
    trust_level = Column(String(40), nullable=False, default="bronze", index=True)
    classification = Column(String(40), nullable=False, default="internal", index=True)
    properties = Column(JSON, default=dict)
    provenance = Column(JSON, default=dict)
    source_refs = Column(JSON, default=list)
    embedding = Column(JSON, default=list)
    embedding_provider = Column(String(80), nullable=True)
    embedding_model = Column(String(50), nullable=True)
    embedding_version = Column(String(80), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    aliases = relationship(
        "KnowledgeGraphAlias",
        back_populates="node",
        cascade="all, delete-orphan",
    )


class KnowledgeGraphAlias(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"node_id": "knowledge_graph_nodes"}
    __tablename__ = "knowledge_graph_aliases"
    __table_args__ = (
        UniqueConstraint("project_scope", "normalized_alias", name="uq_knowledge_graph_aliases_scope_value"),
        Index("ix_knowledge_graph_aliases_node", "node_id"),
        Index("ix_knowledge_graph_aliases_lookup", "project_scope", "normalized_alias"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    # project_scope groups aliases so a normalized alias resolves to one node
    # within a scope. Empty string == instance-global scope.
    project_scope = Column(String(40), nullable=False, default="")
    alias_type = Column(String(60), nullable=False, default="name")
    alias_value = Column(String(500), nullable=False)
    normalized_alias = Column(String(500), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)

    node = relationship("KnowledgeGraphNode", back_populates="aliases")


class KnowledgeGraphEdge(WorkspaceBound, Base):
    __workspace_owners__ = {"source_node_id": "knowledge_graph_nodes"}
    __tablename__ = "knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "edge_type", "source_node_id", "target_node_id",
            name="uq_knowledge_graph_edges_type_nodes",
        ),
        Index("ix_knowledge_graph_edges_source", "source_node_id", "edge_type"),
        Index("ix_knowledge_graph_edges_target", "target_node_id", "edge_type"),
        Index("ix_knowledge_graph_edges_embedding_updated_at", "embedding_updated_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    edge_type = Column(String(60), nullable=False)
    source_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    target_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    description = Column(Text, default="")
    keywords = Column(JSON, default=list)
    weight = Column(Float, default=1.0, nullable=False)
    status = Column(String(40), nullable=False, default="active", index=True)
    trust_level = Column(String(40), nullable=False, default="bronze", index=True)
    properties = Column(JSON, default=dict)
    provenance = Column(JSON, default=dict)
    source_refs = Column(JSON, default=list)
    embedding = Column(JSON, default=list)
    embedding_provider = Column(String(80), nullable=True)
    embedding_model = Column(String(50), nullable=True)
    embedding_version = Column(String(80), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KnowledgeMergeProposal(WorkspaceBound, Base):
    """A fuzzy identity match awaiting human review. Only deterministic identifiers merge at upsert time; entities are
    never silently merged on a fuzzy signal."""
    __workspace_owners__ = {"keep_node_id": "knowledge_graph_nodes"}

    __tablename__ = "knowledge_merge_proposals"
    __table_args__ = (
        UniqueConstraint("keep_node_id", "merge_node_id", name="uq_knowledge_merge_proposals_pair"),
        Index("ix_knowledge_merge_proposals_status", "status"),
        Index("ix_knowledge_merge_proposals_project", "project_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    keep_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    merge_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    reason = Column(Text, nullable=False, default="")
    signal = Column(String(60), nullable=False, default="display_name")
    confidence = Column(Float, nullable=False, default=0.5)
    status = Column(String(30), nullable=False, default="needs_review")
    decided_by = Column(String(36), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KnowledgeCommunity(WorkspaceBound, Base):
    """A cluster of related graph nodes with a summary report (tier 3)."""

    __tablename__ = "knowledge_communities"
    __table_args__ = (
        UniqueConstraint("project_scope", "community_key", name="uq_knowledge_communities_scope_key"),
        Index("ix_knowledge_communities_project", "project_id"),
        Index("ix_knowledge_communities_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    project_scope = Column(String(40), nullable=False, default="")
    community_key = Column(String(120), nullable=False)
    title = Column(String(300), nullable=False, default="")
    summary = Column(Text, default="")
    summary_source = Column(String(30), nullable=False, default="deterministic")
    member_node_ids = Column(JSON, default=list)
    size = Column(Float, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="active")
    embedding = Column(JSON, default=list)
    embedding_provider = Column(String(80), nullable=True)
    embedding_model = Column(String(50), nullable=True)
    embedding_version = Column(String(80), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KnowledgeOntologyVersion(WorkspaceBound, Base):
    """A versioned, reviewable ontology (entity and relation types) per scope. Auto-tuning creates drafts that need
    activation: the ontology never changes silently."""

    __tablename__ = "knowledge_ontology_versions"
    __table_args__ = (
        UniqueConstraint("project_scope", "version", name="uq_knowledge_ontology_versions_scope_version"),
        Index("ix_knowledge_ontology_versions_scope_status", "project_scope", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    project_scope = Column(String(40), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="draft")
    entity_types = Column(JSON, default=list)
    relation_types = Column(JSON, default=list)
    notes = Column(Text, default="")
    created_by = Column(String(36), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KnowledgeClaim(WorkspaceBound, Base):
    """A versioned/temporal fact (GraphRAG covariate) about a subject node."""
    __workspace_owners__ = {"subject_node_id": "knowledge_graph_nodes"}

    __tablename__ = "knowledge_claims"
    __table_args__ = (
        Index("ix_knowledge_claims_subject", "subject_node_id"),
        Index("ix_knowledge_claims_project", "project_id"),
        Index("ix_knowledge_claims_type_status", "claim_type", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    subject_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=False)
    object_node_id = Column(String(36), ForeignKey("knowledge_graph_nodes.id"), nullable=True)
    claim_type = Column(String(80), nullable=False, default="fact")
    statement = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="active")
    # Human version labels (e.g. "v4.0") plus optional real timestamps.
    valid_from_label = Column(String(80), nullable=True)
    valid_until_label = Column(String(80), nullable=True)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    source_refs = Column(JSON, default=list)
    provenance = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
