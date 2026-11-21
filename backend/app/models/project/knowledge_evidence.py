"""PostgreSQL authority for the Workspace Knowledge Evidence ledger.

PostgreSQL owns governance, lineage, and the projection outbox. Object storage is the
blob authority; the Evidence index (``knowledge_evidence_index``) is a rebuildable
projection that can always be reconstructed from these tables plus the stored objects.

Boundaries encoded here:

- every row is Workspace-scoped with a non-null ``project_id``, so no row is ever
  instance-global and visible across Workspaces;
- a source revision is immutable: the content digest, object reference, media type,
  size, and parser identity are written once and never updated;
- an evidence span carries a stable ``evidence_key`` derived from its revision and
  ordinal, which is what a citation resolves through;
- the outbox carries claim, bounded retry, and dead-letter state, so projection is a
  durable transactional handoff instead of a fire-and-forget task.

Failure reasons are fixed state tokens (see ``ALL_PROJECTION_FAILURES``), never server
or driver text, which may carry statement text and values and must not be persisted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now

# Revision lifecycle (contract §3). A revision is registered, then projected. Exactly one
# revision per source is ``projected`` (the source's current content); an older or a
# not-wanted one is ``superseded``, and a removed source's revisions are ``tombstoned``.
# Both stay in the ledger with their spans (history), but leave the Evidence index.
# Re-uploading their exact content registers them again.
REVISION_STATE_REGISTERED = "registered"
REVISION_STATE_PROJECTED = "projected"
REVISION_STATE_SUPERSEDED = "superseded"
REVISION_STATE_TOMBSTONED = "tombstoned"
ALL_REVISION_STATES = frozenset(
    {REVISION_STATE_REGISTERED, REVISION_STATE_PROJECTED, REVISION_STATE_SUPERSEDED, REVISION_STATE_TOMBSTONED}
)

# Outbox lifecycle. ``claimed`` is a lease; ``dead_letter`` is terminal.
OUTBOX_STATE_PENDING = "pending"
OUTBOX_STATE_CLAIMED = "claimed"
OUTBOX_STATE_APPLIED = "applied"
OUTBOX_STATE_DEAD_LETTER = "dead_letter"
ALL_OUTBOX_STATES = frozenset(
    {OUTBOX_STATE_PENDING, OUTBOX_STATE_CLAIMED, OUTBOX_STATE_APPLIED, OUTBOX_STATE_DEAD_LETTER}
)

# Projection operations: write one revision's spans into the Workspace database, add their
# vectors in the Instance's embedding space once the revision is current, or remove them again
# once the revision is superseded or tombstoned. Embedding is its own obligation, so a provider
# outage delays vectors visibly without holding back lexical retrieval.
OUTBOX_OPERATION_PROJECT_REVISION = "project_revision"
OUTBOX_OPERATION_EMBED_REVISION = "embed_revision"
OUTBOX_OPERATION_RETIRE_REVISION = "retire_revision"
# A PDF or Office revision is registered without spans; the sandboxed parser owes them first,
# and only its completion owes the projection.
OUTBOX_OPERATION_PARSE_REVISION = "parse_revision"
# Extract a current revision's spans into the Workspace knowledge graph; owed only by an
# explicit, authorized request, because every span costs governed model calls.
OUTBOX_OPERATION_EXTRACT_GRAPH = "extract_graph"
ALL_OUTBOX_OPERATIONS = frozenset(
    {
        OUTBOX_OPERATION_EXTRACT_GRAPH,
        OUTBOX_OPERATION_PARSE_REVISION,
        OUTBOX_OPERATION_PROJECT_REVISION,
        OUTBOX_OPERATION_EMBED_REVISION,
        OUTBOX_OPERATION_RETIRE_REVISION,
    }
)

# Fixed failure tokens. Persisted instead of a message so no server text is retained.
PROJECTION_FAILURE_NOT_CONFIGURED = "not_configured"
PROJECTION_FAILURE_UNAVAILABLE = "unavailable"
PROJECTION_FAILURE_CONTRACT = "contract_violation"
PROJECTION_FAILURE_LEDGER = "ledger_inconsistent"
# Embedding obligations: the embedding space refused, is not set up, or did not answer.
PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED = "embedding_not_configured"
PROJECTION_FAILURE_EMBEDDING_DENIED = "embedding_denied"
PROJECTION_FAILURE_EMBEDDING_UNAVAILABLE = "embedding_unavailable"
PROJECTION_FAILURE_EMBEDDING_CONTRACT = "embedding_contract"
# Parse obligations: the sandbox is not set up, did not answer, could not parse the document, or
# answered outside its contract (a different parser identity than the revision was registered with).
PROJECTION_FAILURE_PARSER_NOT_CONFIGURED = "parser_not_configured"
PROJECTION_FAILURE_PARSER_UNAVAILABLE = "parser_unavailable"
PROJECTION_FAILURE_PARSER_REFUSED = "parser_refused"
PROJECTION_FAILURE_PARSER_CONTRACT = "parser_contract"
# Graph obligations: the graph store is not set up or did not answer, it answered outside its
# contract, or no governed model may extract for this Workspace.
PROJECTION_FAILURE_GRAPH_NOT_CONFIGURED = "graph_not_configured"
PROJECTION_FAILURE_GRAPH_UNAVAILABLE = "graph_unavailable"
PROJECTION_FAILURE_GRAPH_CONTRACT = "graph_contract"
PROJECTION_FAILURE_GRAPH_MODEL_UNAVAILABLE = "graph_model_unavailable"
ALL_PROJECTION_FAILURES = frozenset(
    {
        PROJECTION_FAILURE_GRAPH_NOT_CONFIGURED,
        PROJECTION_FAILURE_GRAPH_UNAVAILABLE,
        PROJECTION_FAILURE_GRAPH_CONTRACT,
        PROJECTION_FAILURE_GRAPH_MODEL_UNAVAILABLE,
        PROJECTION_FAILURE_PARSER_NOT_CONFIGURED,
        PROJECTION_FAILURE_PARSER_UNAVAILABLE,
        PROJECTION_FAILURE_PARSER_REFUSED,
        PROJECTION_FAILURE_PARSER_CONTRACT,
        PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED,
        PROJECTION_FAILURE_EMBEDDING_DENIED,
        PROJECTION_FAILURE_EMBEDDING_UNAVAILABLE,
        PROJECTION_FAILURE_EMBEDDING_CONTRACT,
        PROJECTION_FAILURE_NOT_CONFIGURED,
        PROJECTION_FAILURE_UNAVAILABLE,
        PROJECTION_FAILURE_CONTRACT,
        PROJECTION_FAILURE_LEDGER,
    }
)

DEFAULT_MAX_PROJECTION_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeEvidenceSource(Base):
    """One logical document inside exactly one Workspace.

    ``source_key`` is the server-derived stable identity of the document within the
    Workspace (not a filesystem path). Its revisions hold the actual content.
    """

    __tablename__ = "knowledge_evidence_sources"
    __table_args__ = (
        UniqueConstraint("project_id", "source_key", name="uq_knowledge_evidence_sources_workspace_key"),
        Index("ix_knowledge_evidence_sources_workspace_created", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    # Non-null by contract: a Knowledge source is never instance-global.
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    source_key = Column(String(200), nullable=False)
    display_title = Column(String(300), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    revisions = relationship(
        "KnowledgeSourceRevision", back_populates="source", cascade="all, delete-orphan", passive_deletes=False
    )


class KnowledgeSourceRevision(Base):
    """One immutable revision of a source: bytes, object reference, and parser identity.

    ``content_sha256`` is unique per source, which is what makes re-uploading identical
    bytes idempotent; different bytes always create a new revision with the next
    ordinal. ``object_key`` is content-addressed and Workspace-partitioned, so it is
    never reused across Workspaces.
    """

    __tablename__ = "knowledge_source_revisions"
    __table_args__ = (
        UniqueConstraint("source_id", "content_sha256", name="uq_knowledge_source_revisions_source_digest"),
        UniqueConstraint("source_id", "revision_ordinal", name="uq_knowledge_source_revisions_source_ordinal"),
        Index("ix_knowledge_source_revisions_workspace_state", "project_id", "state"),
        CheckConstraint("revision_ordinal >= 1", name="ck_knowledge_source_revision_ordinal_positive"),
        CheckConstraint("byte_size >= 0", name="ck_knowledge_source_revision_size_non_negative"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    source_id = Column(String(36), ForeignKey("knowledge_evidence_sources.id"), nullable=False, index=True)
    # Denormalized Workspace scope: every scoped query filters on it directly, and a
    # row can never be read through a join that forgot the Workspace predicate.
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    revision_ordinal = Column(Integer, nullable=False)
    content_sha256 = Column(String(64), nullable=False, index=True)
    byte_size = Column(Integer, nullable=False)
    media_type = Column(String(120), nullable=False)
    object_bucket = Column(String(63), nullable=False)
    object_key = Column(String(1024), nullable=False)
    object_version_id = Column(String(1024), nullable=True)
    # Parser identity is part of lineage: it records which code produced the spans and
    # whether it ran inside a sandbox. In-process text parsing is explicitly unsandboxed.
    parser_name = Column(String(60), nullable=False)
    parser_version = Column(String(30), nullable=False)
    parser_sandbox = Column(String(30), nullable=False)
    state = Column(String(20), nullable=False, default=REVISION_STATE_REGISTERED, index=True)
    span_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    projected_at = Column(DateTime, nullable=True)

    source = relationship("KnowledgeEvidenceSource", back_populates="revisions")
    spans = relationship(
        "KnowledgeEvidenceSpan", back_populates="revision", cascade="all, delete-orphan", passive_deletes=False
    )


class KnowledgeSourceRevisionOrigin(Base):
    """Where exactly one revision came from, as a link a person can open.

    A separate row rather than a revision column: the revision's shape is frozen by its
    adoption contract, and the origin is lineage in its own right. At most one
    per revision, Workspace-scoped like every Evidence row, deleted with the revision.
    """

    __tablename__ = "knowledge_source_revision_origins"
    __table_args__ = (Index("ix_knowledge_source_revision_origins_workspace", "project_id"),)

    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    # Validated absolute http(s) URL without credentials (services/knowledge/sources/source_url.py).
    source_url = Column(String(2048), nullable=False)
    # When the content changed at its source (the source's own date, not our sync); None when it does not say.
    source_changed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeRevisionScope(Base):
    """The products and the version a revision is about.

    Products are labels inside one Workspace (e.g. ``acme-orders``, ``spring-boot``) that are allowed
    to see each other; they narrow retrieval for relevance, and a product that must be sealed off
    lives in its own Workspace instead. ``version`` is the subject version (``4.0``, ``2.3.1``), not
    the ingestion revision. A separate table: adopted revision rows keep their shape.
    """

    __tablename__ = "knowledge_revision_scopes"
    __table_args__ = (Index("ix_knowledge_revision_scopes_workspace", "project_id"),)

    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    products = Column(JSON, nullable=False, default=list)
    version = Column(String(40), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeWorkspaceVectorSpace(Base):
    """An embedding space whose vector property and index exist in the Workspace database.

    Written once the embedding step has ensured them; vector retrieval requires it, so a Workspace
    without vectors answers ``needs_configuration`` instead of failing on a missing index. One row
    per space: spaces never share a property, so several can coexist while an Instance switches.
    """

    __tablename__ = "knowledge_workspace_vector_spaces"

    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    space_key = Column(String(60), primary_key=True)
    ensured_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeSourceHead(Base):
    """Which revision a source currently says, and which one the projection serves.

    ``wanted_revision_id`` follows the latest upload of the source: a new revision, or the
    exact content of an earlier one again. ``current_revision_id`` is the one revision that
    is ``projected``, so default retrieval serves it. The two differ while a projection is
    catching up. ``wanted_revision_id`` is null once the source is tombstoned.

    A separate table rather than source columns: the source's shape is frozen by its
    adoption contract.
    """

    __tablename__ = "knowledge_source_heads"
    __table_args__ = (
        Index("ix_knowledge_source_heads_workspace", "project_id"),
        # Structured reads join a revision to the source whose current revision it is.
        Index("ix_knowledge_source_heads_current_revision", "current_revision_id"),
    )

    source_id = Column(String(36), ForeignKey("knowledge_evidence_sources.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    wanted_revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id"), nullable=True)
    current_revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeEvidenceSpan(Base):
    """One ordered, citable span of a source revision.

    ``evidence_key`` is the stable identity a citation resolves through and the unique
    key of the Evidence index, so the index can be rebuilt without changing
    any citation that was already handed out.
    """

    __tablename__ = "knowledge_evidence_spans"
    __table_args__ = (
        UniqueConstraint("revision_id", "span_ordinal", name="uq_knowledge_evidence_spans_revision_ordinal"),
        UniqueConstraint("project_id", "evidence_key", name="uq_knowledge_evidence_spans_workspace_key"),
        Index("ix_knowledge_evidence_spans_revision_order", "revision_id", "span_ordinal"),
        CheckConstraint("span_ordinal >= 1", name="ck_knowledge_evidence_span_ordinal_positive"),
        CheckConstraint("char_end > char_start", name="ck_knowledge_evidence_span_range_forward"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    span_ordinal = Column(Integer, nullable=False)
    evidence_key = Column(String(128), nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    citation = Column(String(512), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    revision = relationship("KnowledgeSourceRevision", back_populates="spans")


class KnowledgeProjectionOutboxEntry(Base):
    """Transactional outbox entry for projecting one revision into the Evidence index.

    Written in the same transaction as the revision and its spans, so a committed
    revision always has exactly one projection obligation. ``claimed_until`` is the
    lease: an expired claim is reclaimable, which is why a crashed projector does not
    strand the entry.

    ``projected_through_ordinal`` is the persisted cursor of a bounded projection run:
    one run applies a bounded batch of span ordinals and stores how far it got, so a
    revision with thousands of spans is drained over several runs instead of one
    unbounded burst of calls — and partial progress is never recorded as applied.
    """

    __tablename__ = "knowledge_projection_outbox"
    __table_args__ = (
        UniqueConstraint("revision_id", "operation", name="uq_knowledge_projection_outbox_revision_operation"),
        Index("ix_knowledge_projection_outbox_claimable", "state", "next_attempt_at"),
        Index("ix_knowledge_projection_outbox_workspace_state", "project_id", "state"),
        CheckConstraint("attempt_count >= 0", name="ck_knowledge_projection_outbox_attempts_non_negative"),
        CheckConstraint("max_attempts >= 1", name="ck_knowledge_projection_outbox_max_attempts_positive"),
        CheckConstraint("projected_through_ordinal >= 0", name="ck_knowledge_projection_outbox_cursor_non_negative"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id"), nullable=False, index=True)
    operation = Column(String(40), nullable=False, default=OUTBOX_OPERATION_PROJECT_REVISION)
    state = Column(String(20), nullable=False, default=OUTBOX_STATE_PENDING, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=DEFAULT_MAX_PROJECTION_ATTEMPTS)
    # Highest span ordinal already projected for this revision; 0 means nothing yet.
    projected_through_ordinal = Column(Integer, nullable=False, default=0)
    claimed_by = Column(String(64), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    claimed_until = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=False, default=utc_now)
    # One of ``ALL_PROJECTION_FAILURES``; never a server message.
    last_failure = Column(String(40), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
