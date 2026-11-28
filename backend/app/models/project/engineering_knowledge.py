import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class EngineeringKnowledgePack(Base):
    __tablename__ = "engineering_knowledge_packs"
    __table_args__ = (
        UniqueConstraint("key", name="uq_engineering_knowledge_packs_key"),
        Index("ix_engineering_knowledge_packs_stack_status", "stack_key", "lifecycle_status"),
        Index("ix_engineering_knowledge_packs_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(160), nullable=False, index=True)
    name = Column(String(240), nullable=False)
    description = Column(Text, default="")
    stack_key = Column(String(120), nullable=False, index=True)
    lifecycle_status = Column(String(30), nullable=False, default="active", index=True)
    source_policy = Column(JSON, default=dict)
    freshness_policy = Column(JSON, default=dict)
    retrieval_policy = Column(JSON, default=dict)
    toolchain_policy = Column(JSON, default=dict)
    resolution_policy = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    versions = relationship(
        "EngineeringKnowledgePackVersion",
        back_populates="pack",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgePackVersion.version.desc()",
    )
    build_runs = relationship("EngineeringKnowledgePackBuildRun", back_populates="pack", cascade="all, delete-orphan")


class EngineeringKnowledgePackVersion(Base):
    __tablename__ = "engineering_knowledge_pack_versions"
    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_engineering_knowledge_pack_versions_pack_version"),
        Index("ix_engineering_knowledge_pack_versions_pack_status", "pack_id", "status"),
        Index("ix_engineering_knowledge_pack_versions_status_published", "status", "published_at"),
        Index("ix_engineering_knowledge_pack_versions_quality", "quality_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_id = Column(String(36), ForeignKey("engineering_knowledge_packs.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="draft", index=True)
    source_versions = Column(JSON, default=dict)
    target_versions = Column(JSON, default=dict)
    compatibility_facts = Column(JSON, default=dict)
    manifest = Column(JSON, default=dict)
    archive_root = Column(String(1000), nullable=True)
    quality_status = Column(String(30), nullable=False, default="pending", index=True)
    quality_report = Column(JSON, default=dict)
    notes = Column(Text, default="")
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    published_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    published_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack = relationship("EngineeringKnowledgePack", back_populates="versions")
    sources = relationship(
        "EngineeringKnowledgePackSource",
        back_populates="pack_version",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgePackSource.source_key.asc()",
    )
    items = relationship(
        "EngineeringKnowledgePackItem",
        back_populates="pack_version",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgePackItem.retrieval_rank.asc()",
    )
    assignments = relationship(
        "EngineeringKnowledgePackAssignment",
        back_populates="pack_version",
        cascade="all, delete-orphan",
    )
    build_runs = relationship("EngineeringKnowledgePackBuildRun", back_populates="pack_version")


class EngineeringKnowledgePackSource(Base):
    __tablename__ = "engineering_knowledge_pack_sources"
    __table_args__ = (
        UniqueConstraint("pack_version_id", "source_key", name="uq_engineering_knowledge_pack_sources_version_key"),
        Index("ix_engineering_knowledge_pack_sources_version_trust", "pack_version_id", "trust_tier"),
        Index("ix_engineering_knowledge_pack_sources_freshness", "freshness_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_version_id = Column(
        String(36), ForeignKey("engineering_knowledge_pack_versions.id"), nullable=False, index=True
    )
    source_key = Column(String(200), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_uri = Column(String(2000), nullable=False)
    source_type = Column(String(80), nullable=False, index=True)
    trust_tier = Column(String(40), nullable=False, default="official", index=True)
    version_label = Column(String(120), nullable=True, index=True)
    effective_at = Column(DateTime, nullable=True, index=True)
    license_metadata = Column(JSON, default=dict)
    checksum = Column(String(128), nullable=True, index=True)
    fetch_status = Column(String(40), nullable=False, default="pending", index=True)
    freshness_status = Column(String(40), nullable=False, default="unknown", index=True)
    raw_archive_path = Column(String(1000), nullable=True)
    parsed_archive_path = Column(String(1000), nullable=True)
    evidence_archive_path = Column(String(1000), nullable=True)
    source_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack_version = relationship("EngineeringKnowledgePackVersion", back_populates="sources")
    items = relationship("EngineeringKnowledgePackItem", back_populates="source")


class EngineeringKnowledgePackItem(Base):
    __tablename__ = "engineering_knowledge_pack_items"
    __table_args__ = (
        UniqueConstraint("pack_version_id", "item_key", name="uq_engineering_knowledge_pack_items_version_key"),
        Index("ix_engineering_knowledge_pack_items_version_rank", "pack_version_id", "retrieval_rank"),
        Index("ix_engineering_knowledge_pack_items_priority", "retrieval_priority"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_version_id = Column(
        String(36), ForeignKey("engineering_knowledge_pack_versions.id"), nullable=False, index=True
    )
    source_id = Column(String(36), ForeignKey("engineering_knowledge_pack_sources.id"), nullable=True, index=True)
    item_key = Column(String(240), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    content = Column(Text, nullable=False, default="")
    tags = Column(JSON, default=list)
    triggers = Column(JSON, default=list)
    version_scope = Column(JSON, default=dict)
    retrieval_priority = Column(String(30), nullable=False, default="normal", index=True)
    retrieval_rank = Column(Integer, nullable=False, default=100, index=True)
    item_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack_version = relationship("EngineeringKnowledgePackVersion", back_populates="items")
    source = relationship("EngineeringKnowledgePackSource", back_populates="items")


class EngineeringKnowledgePackAssignment(WorkspaceBound, Base):
    __workspace_owners__ = {"repository_id": "code_repositories"}
    __workspace_column__ = "workspace_id"
    __tablename__ = "engineering_knowledge_pack_assignments"
    __table_args__ = (
        Index("ix_engineering_knowledge_pack_assignments_scope", "scope_type", "scope_id"),
        Index("ix_engineering_knowledge_pack_assignments_stack_status", "stack_key", "assignment_status"),
        Index("ix_engineering_knowledge_pack_assignments_priority", "priority"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_version_id = Column(
        String(36), ForeignKey("engineering_knowledge_pack_versions.id"), nullable=False, index=True
    )
    scope_type = Column(String(40), nullable=False, default="global", index=True)
    scope_id = Column(String(200), nullable=True, index=True)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    stack_key = Column(String(120), nullable=False, index=True)
    assignment_status = Column(String(30), nullable=False, default="active", index=True)
    priority = Column(Integer, nullable=False, default=100)
    assignment_policy = Column(JSON, default=dict)
    assigned_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack_version = relationship("EngineeringKnowledgePackVersion", back_populates="assignments")
    workspace = relationship("Project")
    repository = relationship("CodeRepository")


class EngineeringKnowledgePackBuildRun(Base):
    __tablename__ = "engineering_knowledge_pack_build_runs"
    __table_args__ = (
        Index("ix_engineering_knowledge_pack_build_runs_status_started", "status", "started_at"),
        Index("ix_engineering_knowledge_pack_build_runs_stack", "stack_key"),
        Index("ix_engineering_knowledge_pack_build_runs_pack", "pack_id", "started_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_id = Column(String(36), ForeignKey("engineering_knowledge_packs.id"), nullable=True, index=True)
    pack_version_id = Column(
        String(36), ForeignKey("engineering_knowledge_pack_versions.id"), nullable=True, index=True
    )
    trigger = Column(String(60), nullable=False, default="user_prompt", index=True)
    prompt = Column(Text, default="")
    stack_key = Column(String(120), nullable=True, index=True)
    source_versions = Column(JSON, default=dict)
    target_versions = Column(JSON, default=dict)
    status = Column(String(40), nullable=False, default="requested", index=True)
    source_plan = Column(JSON, default=dict)
    acquisition_policy = Column(JSON, default=dict)
    quality_report = Column(JSON, default=dict)
    publish_decision = Column(String(40), nullable=False, default="pending", index=True)
    approval_status = Column(String(40), nullable=False, default="not_required", index=True)
    blocker_details = Column(JSON, default=list)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack = relationship("EngineeringKnowledgePack", back_populates="build_runs")
    pack_version = relationship("EngineeringKnowledgePackVersion", back_populates="build_runs")


class EngineeringKnowledgeRetrievalIndex(Base):
    __tablename__ = "engineering_knowledge_retrieval_index"
    __table_args__ = (
        UniqueConstraint(
            "pack_version_id",
            "record_kind",
            "record_key",
            name="uq_engineering_knowledge_retrieval_version_kind_key",
        ),
        Index("ix_engineering_knowledge_retrieval_active_stack", "is_active", "stack_key"),
        Index("ix_engineering_knowledge_retrieval_kind_active", "record_kind", "is_active"),
        Index("ix_engineering_knowledge_retrieval_version_active", "pack_version_id", "is_active"),
        Index("ix_engineering_knowledge_retrieval_source", "source_key", "source_type"),
        Index("ix_engineering_knowledge_retrieval_trust", "trust_tier"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    pack_id = Column(String(36), ForeignKey("engineering_knowledge_packs.id"), nullable=False, index=True)
    pack_version_id = Column(
        String(36), ForeignKey("engineering_knowledge_pack_versions.id"), nullable=False, index=True
    )
    record_kind = Column(String(40), nullable=False, index=True)
    record_key = Column(String(260), nullable=False, index=True)
    title = Column(String(500), nullable=False, default="")
    summary = Column(Text, default="")
    content = Column(Text, default="")
    search_text = Column(Text, default="")
    stack_key = Column(String(120), nullable=False, index=True)
    source_versions = Column(JSON, default=dict)
    target_versions = Column(JSON, default=dict)
    coverage_areas = Column(JSON, default=list)
    tags = Column(JSON, default=list)
    triggers = Column(JSON, default=list)
    source_key = Column(String(200), nullable=True, index=True)
    source_id = Column(String(36), ForeignKey("engineering_knowledge_pack_sources.id"), nullable=True, index=True)
    source_uri = Column(String(2000), nullable=True)
    source_type = Column(String(80), nullable=True, index=True)
    trust_tier = Column(String(40), nullable=True, index=True)
    freshness_status = Column(String(40), nullable=True, index=True)
    archive_path = Column(String(1000), nullable=True)
    canonical_uri = Column(String(2000), nullable=True)
    record_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=False, nullable=False, index=True)
    indexed_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    pack = relationship("EngineeringKnowledgePack")
    pack_version = relationship("EngineeringKnowledgePackVersion")
    source = relationship("EngineeringKnowledgePackSource")


class EngineeringKnowledgeFederationFeed(Base):
    __tablename__ = "engineering_knowledge_federation_feeds"
    __table_args__ = (
        UniqueConstraint("name", name="uq_engineering_knowledge_federation_feeds_name"),
        Index("ix_engineering_knowledge_federation_feeds_type_status", "feed_type", "status"),
        Index("ix_engineering_knowledge_federation_feeds_publisher", "publisher_instance_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    feed_type = Column(String(40), nullable=False, default="subscriber", index=True)
    publisher_instance_id = Column(String(160), nullable=False, index=True)
    endpoint_url = Column(String(2000), nullable=True)
    sync_mode = Column(String(40), nullable=False, default="manual", index=True)
    status = Column(String(40), nullable=False, default="active", index=True)
    publisher_trust_policy = Column(JSON, default=dict)
    subscriber_policy = Column(JSON, default=dict)
    package_filter = Column(JSON, default=dict)
    signing_key_ref = Column(String(240), nullable=True)
    verification_key_ref = Column(String(240), nullable=True)
    last_sync_at = Column(DateTime, nullable=True, index=True)
    last_sync_status = Column(String(40), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    packages = relationship(
        "EngineeringKnowledgeFederationPackage",
        back_populates="feed",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgeFederationPackage.created_at.desc()",
    )
    sync_runs = relationship(
        "EngineeringKnowledgeFederationSyncRun",
        back_populates="feed",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgeFederationSyncRun.started_at.desc()",
    )


class EngineeringKnowledgeFederationPackage(Base):
    __tablename__ = "engineering_knowledge_federation_packages"
    __table_args__ = (
        UniqueConstraint(
            "direction",
            "publisher_instance_id",
            "package_id",
            "package_checksum",
            name="uq_engineering_knowledge_federation_package_checksum",
        ),
        Index("ix_engineering_knowledge_federation_packages_feed", "feed_id", "created_at"),
        Index("ix_engineering_knowledge_federation_packages_status_review", "status", "review_status"),
        Index("ix_engineering_knowledge_federation_packages_package", "publisher_instance_id", "package_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    feed_id = Column(String(36), ForeignKey("engineering_knowledge_federation_feeds.id"), nullable=True, index=True)
    direction = Column(String(40), nullable=False, index=True)
    package_id = Column(String(80), nullable=False, index=True)
    publisher_instance_id = Column(String(160), nullable=False, index=True)
    schema_version = Column(String(80), nullable=False)
    package_checksum = Column(String(64), nullable=False, index=True)
    signature = Column(JSON, default=dict)
    content_json = Column(JSON, nullable=False)
    classification = Column(String(40), nullable=False, index=True)
    trust_level = Column(String(40), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="pending_review", index=True)
    review_status = Column(String(40), nullable=False, default="pending_review", index=True)
    version = Column(Integer, nullable=False, default=1)
    dry_run_result = Column(JSON, default=dict)
    conflicts = Column(JSON, default=list)
    retraction_refs = Column(JSON, default=list)
    source_package_record_id = Column(
        String(36), ForeignKey("engineering_knowledge_federation_packages.id"), nullable=True, index=True
    )
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    feed = relationship("EngineeringKnowledgeFederationFeed", back_populates="packages")
    sync_runs = relationship("EngineeringKnowledgeFederationSyncRun", back_populates="package_record")


class EngineeringKnowledgeFederationSyncRun(Base):
    __tablename__ = "engineering_knowledge_federation_sync_runs"
    __table_args__ = (
        Index("ix_engineering_knowledge_federation_sync_runs_feed_started", "feed_id", "started_at"),
        Index("ix_engineering_knowledge_federation_sync_runs_status_started", "status", "started_at"),
        Index("ix_engineering_knowledge_federation_sync_runs_operation_started", "operation", "started_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    feed_id = Column(String(36), ForeignKey("engineering_knowledge_federation_feeds.id"), nullable=True, index=True)
    package_record_id = Column(
        String(36), ForeignKey("engineering_knowledge_federation_packages.id"), nullable=True, index=True
    )
    operation = Column(String(60), nullable=False, index=True)
    status = Column(String(40), nullable=False, index=True)
    package_id = Column(String(80), nullable=True, index=True)
    package_checksum = Column(String(64), nullable=True, index=True)
    result = Column(JSON, default=dict)
    errors = Column(JSON, default=list)
    started_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    feed = relationship("EngineeringKnowledgeFederationFeed", back_populates="sync_runs")
    package_record = relationship("EngineeringKnowledgeFederationPackage", back_populates="sync_runs")


class EngineeringKnowledgeGraphNode(WorkspaceBound, Base):
    __workspace_owners__ = {"repository_id": "code_repositories"}
    __workspace_column__ = "workspace_id"
    __tablename__ = "engineering_knowledge_graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "node_type",
            "node_key",
            name="uq_engineering_knowledge_graph_nodes_scope_type_key",
        ),
        Index("ix_engineering_knowledge_graph_nodes_type_status", "node_type", "status"),
        Index("ix_engineering_knowledge_graph_nodes_scope", "scope_type", "scope_key"),
        Index("ix_engineering_knowledge_graph_nodes_trust", "trust_level", "classification"),
        Index("ix_engineering_knowledge_graph_nodes_validity", "valid_from", "valid_until"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    node_type = Column(String(60), nullable=False, index=True)
    node_key = Column(String(300), nullable=False, index=True)
    display_name = Column(String(500), nullable=False, default="")
    summary = Column(Text, default="")
    status = Column(String(40), nullable=False, default="active", index=True)
    scope_type = Column(String(40), nullable=False, default="global", index=True)
    scope_id = Column(String(200), nullable=True, index=True)
    scope_key = Column(String(260), nullable=False, default="global:global", index=True)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    trust_level = Column(String(40), nullable=False, default="bronze", index=True)
    classification = Column(String(40), nullable=False, default="internal", index=True)
    valid_from = Column(DateTime, nullable=True, index=True)
    valid_until = Column(DateTime, nullable=True, index=True)
    properties_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)
    source_refs_json = Column(JSON, default=list)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    aliases = relationship(
        "EngineeringKnowledgeGraphAlias",
        back_populates="node",
        cascade="all, delete-orphan",
        order_by="EngineeringKnowledgeGraphAlias.alias_type.asc()",
    )
    outgoing_edges = relationship(
        "EngineeringKnowledgeGraphEdge",
        foreign_keys="EngineeringKnowledgeGraphEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "EngineeringKnowledgeGraphEdge",
        foreign_keys="EngineeringKnowledgeGraphEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )
    workspace = relationship("Project", foreign_keys=[workspace_id])
    repository = relationship("CodeRepository", foreign_keys=[repository_id])


class EngineeringKnowledgeGraphAlias(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"node_id": "engineering_knowledge_graph_nodes"}
    __tablename__ = "engineering_knowledge_graph_aliases"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "alias_type",
            "normalized_alias",
            name="uq_engineering_knowledge_graph_aliases_scope_type_value",
        ),
        Index("ix_engineering_knowledge_graph_aliases_node", "node_id"),
        Index("ix_engineering_knowledge_graph_aliases_lookup", "scope_key", "normalized_alias"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    node_id = Column(String(36), ForeignKey("engineering_knowledge_graph_nodes.id"), nullable=False, index=True)
    alias_type = Column(String(60), nullable=False, default="name", index=True)
    alias_value = Column(String(500), nullable=False)
    normalized_alias = Column(String(500), nullable=False, index=True)
    scope_key = Column(String(260), nullable=False, default="global:global", index=True)
    provenance_json = Column(JSON, default=dict)
    source_refs_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    node = relationship("EngineeringKnowledgeGraphNode", back_populates="aliases")


class EngineeringKnowledgeGraphEdge(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"source_node_id": "engineering_knowledge_graph_nodes"}
    __tablename__ = "engineering_knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "edge_type",
            "source_node_id",
            "target_node_id",
            name="uq_engineering_knowledge_graph_edges_scope_type_nodes",
        ),
        Index("ix_engineering_knowledge_graph_edges_source", "source_node_id", "edge_type"),
        Index("ix_engineering_knowledge_graph_edges_target", "target_node_id", "edge_type"),
        Index("ix_engineering_knowledge_graph_edges_scope", "scope_type", "scope_key"),
        Index("ix_engineering_knowledge_graph_edges_trust", "trust_level", "classification"),
        Index("ix_engineering_knowledge_graph_edges_validity", "valid_from", "valid_until"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    edge_type = Column(String(60), nullable=False, index=True)
    source_node_id = Column(String(36), ForeignKey("engineering_knowledge_graph_nodes.id"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("engineering_knowledge_graph_nodes.id"), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="active", index=True)
    scope_type = Column(String(40), nullable=False, default="global", index=True)
    scope_id = Column(String(200), nullable=True, index=True)
    scope_key = Column(String(260), nullable=False, default="global:global", index=True)
    trust_level = Column(String(40), nullable=False, default="bronze", index=True)
    classification = Column(String(40), nullable=False, default="internal", index=True)
    valid_from = Column(DateTime, nullable=True, index=True)
    valid_until = Column(DateTime, nullable=True, index=True)
    properties_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)
    source_refs_json = Column(JSON, default=list)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    source_node = relationship(
        "EngineeringKnowledgeGraphNode",
        foreign_keys=[source_node_id],
        back_populates="outgoing_edges",
    )
    target_node = relationship(
        "EngineeringKnowledgeGraphNode",
        foreign_keys=[target_node_id],
        back_populates="incoming_edges",
    )


__all__ = [
    "EngineeringKnowledgeFederationFeed",
    "EngineeringKnowledgeFederationPackage",
    "EngineeringKnowledgeFederationSyncRun",
    "EngineeringKnowledgeGraphAlias",
    "EngineeringKnowledgeGraphEdge",
    "EngineeringKnowledgeGraphNode",
    "EngineeringKnowledgePack",
    "EngineeringKnowledgePackAssignment",
    "EngineeringKnowledgePackBuildRun",
    "EngineeringKnowledgePackItem",
    "EngineeringKnowledgeRetrievalIndex",
    "EngineeringKnowledgePackSource",
    "EngineeringKnowledgePackVersion",
]
