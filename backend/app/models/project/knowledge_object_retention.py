"""Operator-owned retention governance for Workspace Knowledge objects.

The ingestion boundary writes an immutable content-addressed object *before* it
commits the revision/outbox transaction, so a failed ledger insert can leave bytes
behind that no governed reference points at. These tables are the governance record of
finding those bytes (report-only: no product path deletes them):

- ``KnowledgeObjectRetentionPolicy`` is the operator's explicit per-Workspace retention
  record (mode, age bound, legal hold). An absent row means the report-only default.
- ``KnowledgeObjectReconciliationRun`` is one comparison of the governed ledger
  references against the object inventory: counts only, so a run record discloses nothing
  about content.
- ``KnowledgeObjectReconciliationFinding`` is one unreferenced object of one run: which
  content address, how many bytes, how old.
- ``KnowledgeObjectRetentionHold`` is the durable claim of an operator retention pass on one
  object. It is unique on ``(project_id, object_key)``, and the ingestion path refuses to
  register a revision for a held key.

Boundaries encoded here:

- every row is Workspace-scoped with a non-null ``project_id``; nothing is instance-global;
- ``object_key`` and ``content_sha256`` are persisted because an operator needs the exact
  address and content of an unreferenced object — they are **never** rendered into an
  API payload, a tool result or a log line (see ``services/knowledge/retention``);
- failure and state values are fixed tokens (``ALL_*`` below), never server or driver text,
  so no S3 error body, endpoint or credential can be persisted;
- no bucket, endpoint, region or credential column exists at all: where the bytes live is
  deployment configuration owned by ``services/knowledge/objects``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from ...db import Base
from ...time_utils import utc_now

# Retention modes. ``report_only`` is the default *and* the value of an absent row.
RETENTION_MODE_REPORT_ONLY = "report_only"
ALL_RETENTION_MODES = frozenset({RETENTION_MODE_REPORT_ONLY})

# How old an unreferenced object must be before it is age-eligible. The lower bound
# exists so no policy can shrink the window below any plausible in-flight ingestion.
DEFAULT_MIN_OBJECT_AGE_HOURS = 168
MIN_OBJECT_AGE_HOURS = 1
MAX_OBJECT_AGE_HOURS = 8760

# Run lifecycle. A run either completed its bounded inventory comparison or failed.
RUN_STATE_COMPLETED = "completed"
RUN_STATE_FAILED = "failed"
ALL_RUN_STATES = frozenset({RUN_STATE_COMPLETED, RUN_STATE_FAILED})

# Finding lifecycle: ``observed`` by the newest run, ``superseded`` once a newer run replaced it.
FINDING_STATE_OBSERVED = "observed"
FINDING_STATE_SUPERSEDED = "superseded"
ALL_FINDING_STATES = frozenset({FINDING_STATE_OBSERVED, FINDING_STATE_SUPERSEDED})

# Fixed failure tokens of a failed run. Persisted instead of a message so no S3 or driver text is retained.
RETENTION_FAILURE_NOT_CONFIGURED = "not_configured"
RETENTION_FAILURE_UNAVAILABLE = "unavailable"
RETENTION_FAILURE_UNAUTHORIZED = "unauthorized"
RETENTION_FAILURE_NOT_FOUND = "not_found"
RETENTION_FAILURE_CONTRACT = "contract_violation"
ALL_RETENTION_FAILURES = frozenset(
    {
        RETENTION_FAILURE_NOT_CONFIGURED,
        RETENTION_FAILURE_UNAVAILABLE,
        RETENTION_FAILURE_UNAUTHORIZED,
        RETENTION_FAILURE_NOT_FOUND,
        RETENTION_FAILURE_CONTRACT,
    }
)

# Operator identity token of a run or a hold (``cli:<name>`` / ``api:<user id>``).
MAX_OPERATOR_CHARS = 64


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeObjectRetentionPolicy(Base):
    """The explicit, operator-owned retention record of one Workspace.

    Absent means report-only. ``mode``, ``legal_hold`` and the bounds are recorded with the
    operator who set them.
    """

    __tablename__ = "knowledge_object_retention_policies"
    __table_args__ = (
        CheckConstraint(
            f"min_object_age_hours >= {MIN_OBJECT_AGE_HOURS} "
            f"AND min_object_age_hours <= {MAX_OBJECT_AGE_HOURS}",
            name="ck_knowledge_object_retention_age_bounds",
        ),
    )

    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    mode = Column(String(30), nullable=False, default=RETENTION_MODE_REPORT_ONLY)
    min_object_age_hours = Column(Integer, nullable=False, default=DEFAULT_MIN_OBJECT_AGE_HOURS)
    legal_hold = Column(Boolean, nullable=False, default=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeObjectReconciliationRun(Base):
    """One bounded comparison of governed ledger references against the object inventory.

    Counts only. ``inventory_truncated`` records that the bounded page budget was reached,
    so a partial view is never mistaken for a complete one, and
    ``unrecognized_object_count`` records keys under the Workspace prefix that do not match
    the product's key derivation: they are counted, never named.
    """

    __tablename__ = "knowledge_object_reconciliation_runs"
    __table_args__ = (
        Index("ix_knowledge_object_reconciliation_runs_workspace_started", "project_id", "started_at"),
        CheckConstraint(
            "inventory_object_count >= 0 AND referenced_object_count >= 0 "
            "AND unreferenced_object_count >= 0 AND unrecognized_object_count >= 0 "
            "AND candidate_object_count >= 0 AND unreferenced_byte_size >= 0",
            name="ck_knowledge_object_reconciliation_counts_non_negative",
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    # The policy mode and age bound that were in effect for this run.
    mode = Column(String(30), nullable=False, default=RETENTION_MODE_REPORT_ONLY)
    min_object_age_hours = Column(Integer, nullable=False, default=DEFAULT_MIN_OBJECT_AGE_HOURS)
    state = Column(String(20), nullable=False, default=RUN_STATE_COMPLETED, index=True)
    # One of ``ALL_RETENTION_FAILURES``; never a server message.
    failure = Column(String(40), nullable=True)
    inventory_object_count = Column(Integer, nullable=False, default=0)
    referenced_object_count = Column(Integer, nullable=False, default=0)
    unreferenced_object_count = Column(Integer, nullable=False, default=0)
    unrecognized_object_count = Column(Integer, nullable=False, default=0)
    candidate_object_count = Column(Integer, nullable=False, default=0)
    unreferenced_byte_size = Column(Integer, nullable=False, default=0)
    inventory_truncated = Column(Boolean, nullable=False, default=False)
    requested_by = Column(String(MAX_OPERATOR_CHARS), nullable=False)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime, nullable=True)


class KnowledgeObjectReconciliationFinding(Base):
    """One unreferenced object of one run.

    ``object_key`` is the exact address and ``content_sha256`` names *what* is stored; neither
    ever leaves the service layer. A newer run supersedes older observations.
    """

    __tablename__ = "knowledge_object_reconciliation_findings"
    __table_args__ = (
        UniqueConstraint("run_id", "object_key", name="uq_knowledge_object_finding_run_key"),
        Index("ix_knowledge_object_findings_workspace_state", "project_id", "state"),
        CheckConstraint(
            "byte_size >= 0 AND observed_age_hours >= 0",
            name="ck_knowledge_object_finding_measures_non_negative",
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(
        String(36), ForeignKey("knowledge_object_reconciliation_runs.id"), nullable=False, index=True
    )
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    object_key = Column(String(1024), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    object_last_modified = Column(DateTime, nullable=False)
    observed_age_hours = Column(Integer, nullable=False)
    # False means the object is younger than the policy bound.
    age_eligible = Column(Boolean, nullable=False, default=False)
    state = Column(String(30), nullable=False, default=FINDING_STATE_OBSERVED, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeObjectRetentionHold(Base):
    """The durable claim of an operator retention pass on one object.

    Unique on ``(project_id, object_key)``: a second pass loses the unique constraint, and the
    ingestion path refuses to register a revision whose object is held. ``expires_at`` bounds a hold whose
    operator process died, so a crashed pass cannot park a key forever.
    """

    __tablename__ = "knowledge_object_retention_holds"
    __table_args__ = (
        UniqueConstraint("project_id", "object_key", name="uq_knowledge_object_hold_workspace_key"),
        Index("ix_knowledge_object_holds_expiry", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    object_key = Column(String(1024), nullable=False)
    finding_id = Column(
        String(36), ForeignKey("knowledge_object_reconciliation_findings.id"), nullable=False, index=True
    )
    acquired_by = Column(String(MAX_OPERATOR_CHARS), nullable=False)
    acquired_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=False)
