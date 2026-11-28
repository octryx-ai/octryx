import uuid

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class CodeRepository(WorkspaceBound, Base):
    __tablename__ = "code_repositories"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    repo_root = Column(String(1000), nullable=False)
    provider = Column(String(40), nullable=False, default="local", index=True)
    remote_url = Column(String(1000), nullable=True)
    default_branch = Column(String(120), nullable=True)
    index_backend = Column(String(80), nullable=False, default="ripgrep", index=True)
    semantic_backend = Column(String(80), nullable=False, default="regex", index=True)
    structure_backend = Column(String(80), nullable=False, default="regex", index=True)
    graph_backend = Column(String(80), nullable=False, default="disabled", index=True)
    config_json = Column(JSON, default=dict)
    capabilities_json = Column(JSON, default=dict)
    latest_index_summary = Column(JSON, default=dict)
    last_index_status = Column(String(40), nullable=True, index=True)
    last_indexed_at = Column(DateTime, nullable=True, index=True)
    last_indexed_commit = Column(String(64), nullable=True, index=True)
    last_index_error = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    project = relationship("Project")
    index_runs = relationship(
        "CodeIndexRun",
        back_populates="repository",
        cascade="all, delete-orphan",
        order_by="CodeIndexRun.started_at.desc()",
    )


class CodeIndexRun(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"repository_id": "code_repositories"}
    __tablename__ = "code_index_runs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="queued", index=True)
    trigger = Column(String(40), nullable=False, default="manual", index=True)
    index_backend = Column(String(80), nullable=False, default="ripgrep")
    semantic_backend = Column(String(80), nullable=False, default="regex")
    structure_backend = Column(String(80), nullable=False, default="regex")
    graph_backend = Column(String(80), nullable=False, default="disabled")
    files_indexed = Column(Integer, nullable=False, default=0)
    symbols_indexed = Column(Integer, nullable=False, default=0)
    references_indexed = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    storage_path = Column(String(1000), nullable=True)
    languages_json = Column(JSON, default=dict)
    summary_json = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    finished_at = Column(DateTime, nullable=True, index=True)

    repository = relationship("CodeRepository", back_populates="index_runs")


class CodeGraphRepository(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_repositories"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=False, unique=True, index=True)
    graph_backend = Column(String(80), nullable=False, default="native", index=True)
    graph_schema_version = Column(String(40), nullable=False, default="v1", index=True)
    indexing_mode = Column(String(80), nullable=False, default="incremental", index=True)
    backend_metadata = Column(JSON, default=dict)
    config_json = Column(JSON, default=dict)
    latest_run_id = Column(String(36), nullable=True, index=True)
    staleness_state = Column(String(40), nullable=False, default="unknown", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    code_repository = relationship("CodeRepository", lazy="joined")
    runs = relationship(
        "CodeGraphRun",
        back_populates="graph_repository",
        cascade="all, delete-orphan",
        order_by="CodeGraphRun.started_at.desc()",
    )
    staleness_entries = relationship(
        "CodeGraphStaleness",
        back_populates="graph_repository",
        cascade="all, delete-orphan",
        order_by="CodeGraphStaleness.file_path",
    )


class CodeGraphRun(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_runs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=False, index=True)
    commit_hash = Column(String(64), nullable=True, index=True)
    status = Column(String(40), nullable=False, default="queued", index=True)
    trigger = Column(String(40), nullable=False, default="manual", index=True)
    backend = Column(String(80), nullable=False, default="native", index=True)
    file_count = Column(Integer, nullable=False, default=0)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    unresolved_reference_count = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    run_metadata = Column(JSON, default=dict)
    staleness_reason = Column(Text, nullable=True)
    is_stale = Column(Boolean, nullable=False, default=False, index=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    finished_at = Column(DateTime, nullable=True, index=True)

    graph_repository = relationship("CodeGraphRepository", back_populates="runs")
    code_repository = relationship("CodeRepository")
    files = relationship(
        "CodeGraphFile",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphFile.file_path",
    )
    nodes = relationship(
        "CodeGraphNode",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphNode.node_type",
    )
    edges = relationship(
        "CodeGraphEdge",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphEdge.relation",
    )
    unresolved_references = relationship(
        "CodeGraphUnresolvedReference",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphUnresolvedReference.symbol_text",
    )
    symbols = relationship(
        "CodeGraphSymbol",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphSymbol.name",
    )
    references = relationship(
        "CodeGraphReference",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphReference.reference_name",
    )
    routes = relationship(
        "CodeGraphRoute",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphRoute.route_path",
    )
    chunks = relationship(
        "CodeGraphChunk",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphChunk.path",
    )
    snapshots = relationship(
        "CodeGraphSnapshot",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CodeGraphSnapshot.snapshot_kind",
    )
    staleness_entries = relationship(
        "CodeGraphStaleness",
        back_populates="run",
        order_by="CodeGraphStaleness.file_path",
    )


class CodeGraphFile(Base):
    __tablename__ = "code_graph_files"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    file_path = Column(String(1024), nullable=False, index=True)
    language = Column(String(120), nullable=False, default="unknown", index=True)
    file_hash = Column(String(128), nullable=True, index=True)
    mtime_ns = Column(BigInteger, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    line_count = Column(Integer, nullable=True)
    parse_error = Column(Text, nullable=True)
    is_binary = Column(Boolean, nullable=False, default=False, index=True)
    is_stale = Column(Boolean, nullable=False, default=False, index=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    file_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="files")
    nodes = relationship(
        "CodeGraphNode",
        back_populates="source_file",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("run_id", "file_path", name="uq_code_graph_file_run_path"),
    )


class CodeGraphNode(Base):
    __tablename__ = "code_graph_nodes"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    source_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    external_id = Column(String(255), nullable=False)
    node_type = Column(String(80), nullable=False, index=True)
    name = Column(String(512), nullable=False, index=True)
    language = Column(String(120), nullable=False, default="unknown", index=True)
    signature = Column(String(1024), nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    path = Column(String(1024), nullable=True, index=True)
    confidence = Column(String(30), nullable=False, default="EXTRACTED", index=True)
    parse_error = Column(Text, nullable=True)
    is_stale = Column(Boolean, nullable=False, default=False, index=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    node_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="nodes")
    source_file = relationship("CodeGraphFile", back_populates="nodes")
    outgoing_edges = relationship(
        "CodeGraphEdge",
        back_populates="source_node",
        foreign_keys="CodeGraphEdge.source_node_id",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "CodeGraphEdge",
        back_populates="target_node",
        foreign_keys="CodeGraphEdge.target_node_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("run_id", "external_id", name="uq_code_graph_node_run_external_id"),
    )


class CodeGraphEdge(Base):
    __tablename__ = "code_graph_edges"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    source_node_id = Column(String(36), ForeignKey("code_graph_nodes.id"), nullable=False, index=True)
    target_node_id = Column(String(36), ForeignKey("code_graph_nodes.id"), nullable=False, index=True)
    relation = Column(String(120), nullable=False, index=True)
    confidence = Column(String(30), nullable=False, default="EXTRACTED", index=True)
    is_directed = Column(Boolean, nullable=False, default=True)
    edge_metadata = Column(JSON, default=dict)
    parse_error = Column(Text, nullable=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="edges")
    source_node = relationship("CodeGraphNode", back_populates="outgoing_edges", foreign_keys=[source_node_id])
    target_node = relationship("CodeGraphNode", back_populates="incoming_edges", foreign_keys=[target_node_id])

    __table_args__ = (
        UniqueConstraint("run_id", "source_node_id", "target_node_id", "relation", name="uq_code_graph_edge_identity"),
    )


class CodeGraphUnresolvedReference(Base):
    __tablename__ = "code_graph_unresolved_references"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    source_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    symbol_text = Column(String(500), nullable=False, index=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    reference_context = Column(Text, nullable=True)
    confidence = Column(String(30), nullable=False, default="AMBIGUOUS", index=True)
    unresolved_reason = Column(String(255), nullable=False, default="unresolved_reference", index=True)
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="unresolved_references")
    source_file = relationship("CodeGraphFile")

    __table_args__ = (
        UniqueConstraint("run_id", "symbol_text", "line_start", name="uq_code_graph_unresolved_reference"),
    )

class CodeGraphSymbol(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_symbols"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    source_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    node_id = Column(String(36), ForeignKey("code_graph_nodes.id"), nullable=True, index=True)
    stable_symbol_id = Column(String(512), nullable=False)
    kind = Column(String(80), nullable=False, index=True)
    name = Column(String(512), nullable=False, index=True)
    qualified_name = Column(String(1024), nullable=True, index=True)
    signature = Column(String(1024), nullable=True)
    docstring_excerpt = Column(Text, nullable=True)
    visibility = Column(String(40), nullable=True, index=True)
    is_exported = Column(Boolean, nullable=False, default=False, index=True)
    is_static = Column(Boolean, nullable=False, default=False, index=True)
    is_async = Column(Boolean, nullable=False, default=False, index=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    column_start = Column(Integer, nullable=True)
    column_end = Column(Integer, nullable=True)
    parent_symbol_id = Column(String(36), ForeignKey("code_graph_symbols.id"), nullable=True, index=True)
    extraction_backend = Column(String(80), nullable=False, default="native", index=True)
    confidence = Column(String(30), nullable=False, default="EXTRACTED", index=True)
    symbol_metadata = Column(JSON, default=dict)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="symbols")
    source_file = relationship("CodeGraphFile")
    node = relationship("CodeGraphNode")
    parent_symbol = relationship("CodeGraphSymbol", remote_side=[id])

    __table_args__ = (
        UniqueConstraint("run_id", "stable_symbol_id", name="uq_code_graph_symbol_run_stable_id"),
    )


class CodeGraphReference(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_references"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    source_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    source_symbol_id = Column(String(36), ForeignKey("code_graph_symbols.id"), nullable=True, index=True)
    target_symbol_id = Column(String(36), ForeignKey("code_graph_symbols.id"), nullable=True, index=True)
    edge_id = Column(String(36), ForeignKey("code_graph_edges.id"), nullable=True, index=True)
    reference_name = Column(String(512), nullable=False, index=True)
    reference_kind = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="unresolved", index=True)
    candidates_json = Column(JSON, default=list)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    column_start = Column(Integer, nullable=True)
    column_end = Column(Integer, nullable=True)
    confidence = Column(String(30), nullable=False, default="AMBIGUOUS", index=True)
    reference_metadata = Column(JSON, default=dict)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="references")
    source_file = relationship("CodeGraphFile")
    source_symbol = relationship("CodeGraphSymbol", foreign_keys=[source_symbol_id])
    target_symbol = relationship("CodeGraphSymbol", foreign_keys=[target_symbol_id])
    edge = relationship("CodeGraphEdge")

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_file_id",
            "reference_name",
            "reference_kind",
            "line_start",
            name="uq_code_graph_reference_identity",
        ),
    )


class CodeGraphRoute(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_routes"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    router_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    route_node_id = Column(String(36), ForeignKey("code_graph_nodes.id"), nullable=True, index=True)
    handler_symbol_id = Column(String(36), ForeignKey("code_graph_symbols.id"), nullable=True, index=True)
    method = Column(String(40), nullable=False, index=True)
    route_path = Column(String(1024), nullable=False, index=True)
    framework = Column(String(80), nullable=False, index=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    confidence = Column(String(30), nullable=False, default="EXTRACTED", index=True)
    route_metadata = Column(JSON, default=dict)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="routes")
    router_file = relationship("CodeGraphFile")
    route_node = relationship("CodeGraphNode")
    handler_symbol = relationship("CodeGraphSymbol")

    __table_args__ = (
        UniqueConstraint("run_id", "framework", "method", "route_path", name="uq_code_graph_route_identity"),
    )


class CodeGraphChunk(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_chunks"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True, index=True)
    source_file_id = Column(String(36), ForeignKey("code_graph_files.id"), nullable=True, index=True)
    source_symbol_id = Column(String(36), ForeignKey("code_graph_symbols.id"), nullable=True, index=True)
    chunk_kind = Column(String(80), nullable=False, default="file", index=True)
    path = Column(String(1024), nullable=True, index=True)
    line_start = Column(Integer, nullable=False, default=1)
    line_end = Column(Integer, nullable=False, default=1)
    token_estimate = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=True)
    content_hash = Column(String(128), nullable=True, index=True)
    chunk_metadata = Column(JSON, default=dict)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="chunks")
    source_file = relationship("CodeGraphFile")
    source_symbol = relationship("CodeGraphSymbol")

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_file_id",
            "source_symbol_id",
            "chunk_kind",
            "line_start",
            "line_end",
            name="uq_code_graph_chunk_identity",
        ),
    )


class CodeGraphSnapshot(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_snapshots"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=False, index=True)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=False, index=True)
    snapshot_kind = Column(String(80), nullable=False, default="index", index=True)
    artifact_path = Column(String(1000), nullable=True)
    content_hash = Column(String(128), nullable=True, index=True)
    file_count = Column(Integer, nullable=False, default=0)
    symbol_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    snapshot_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)

    run = relationship("CodeGraphRun", back_populates="snapshots")
    code_repository = relationship("CodeRepository")

    __table_args__ = (
        UniqueConstraint("run_id", "snapshot_kind", name="uq_code_graph_snapshot_run_kind"),
    )


class CodeGraphStaleness(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"code_repository_id": "code_repositories"}
    __tablename__ = "code_graph_staleness"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    graph_repository_id = Column(String(36), ForeignKey("code_graph_repositories.id"), nullable=False, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("code_graph_runs.id"), nullable=True, index=True)
    file_path = Column(String(1024), nullable=False, index=True)
    observed_hash = Column(String(128), nullable=True, index=True)
    observed_mtime_ns = Column(BigInteger, nullable=True)
    indexed_hash = Column(String(128), nullable=True, index=True)
    indexed_mtime_ns = Column(BigInteger, nullable=True)
    status = Column(String(40), nullable=False, default="fresh", index=True)
    reason = Column(Text, nullable=True)
    staleness_metadata = Column(JSON, default=dict)
    checked_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    graph_repository = relationship("CodeGraphRepository", back_populates="staleness_entries")
    code_repository = relationship("CodeRepository")
    run = relationship("CodeGraphRun", back_populates="staleness_entries")

    __table_args__ = (
        UniqueConstraint("graph_repository_id", "file_path", name="uq_code_graph_staleness_file"),
    )
