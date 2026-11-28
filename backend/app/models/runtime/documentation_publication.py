"""Documentation publish and prove: durable documentation write intents and audience receipts."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from .governed_revision import in_list


def uuid_pk() -> str:
    return str(uuid.uuid4())


INTENT_RESERVED = "reserved"
INTENT_APPROVED = "approved"
INTENT_SEND_STARTED = "send_started"
INTENT_SENT_CONFIRMED = "sent_confirmed"
INTENT_PENDING_RECONCILE = "pending_reconcile"
INTENT_NEVER_STARTED_CERTIFIED = "never_started_certified"
INTENT_SUPERSEDED = "superseded"

INTENT_STATES: tuple[str, ...] = (
    INTENT_RESERVED,
    INTENT_APPROVED,
    INTENT_SEND_STARTED,
    INTENT_SENT_CONFIRMED,
    INTENT_PENDING_RECONCILE,
    INTENT_NEVER_STARTED_CERTIFIED,
    INTENT_SUPERSEDED,
)
# A request may have reached the provider: reconcile before any new write; never superseded or resent.
INTENT_POTENTIALLY_SENT_STATES: frozenset[str] = frozenset({INTENT_SEND_STARTED, INTENT_PENDING_RECONCILE})
# The only states a sender may claim from.
INTENT_SENDABLE_STATES: frozenset[str] = frozenset({INTENT_APPROVED, INTENT_NEVER_STARTED_CERTIFIED})
# The states that hold the run's documentation slot (partial unique index).
INTENT_ACTIVE_STATES: tuple[str, ...] = (
    INTENT_RESERVED,
    INTENT_APPROVED,
    INTENT_SEND_STARTED,
    INTENT_PENDING_RECONCILE,
    INTENT_NEVER_STARTED_CERTIFIED,
)
# The states in which exactly one sender holds the claim.
INTENT_CLAIMED_STATES: tuple[str, ...] = (INTENT_SEND_STARTED, INTENT_SENT_CONFIRMED, INTENT_PENDING_RECONCILE)
# The states that carry the approval (decision, card hash, approved body hash).
INTENT_APPROVED_STATES: tuple[str, ...] = (
    INTENT_APPROVED,
    INTENT_SEND_STARTED,
    INTENT_SENT_CONFIRMED,
    INTENT_PENDING_RECONCILE,
    INTENT_NEVER_STARTED_CERTIFIED,
)

INTENT_TRANSITIONS: dict[str, frozenset[str]] = {
    INTENT_RESERVED: frozenset({INTENT_APPROVED, INTENT_SUPERSEDED}),
    INTENT_APPROVED: frozenset({INTENT_SEND_STARTED, INTENT_SUPERSEDED}),
    INTENT_SEND_STARTED: frozenset({INTENT_SENT_CONFIRMED, INTENT_PENDING_RECONCILE, INTENT_NEVER_STARTED_CERTIFIED}),
    INTENT_PENDING_RECONCILE: frozenset({INTENT_SENT_CONFIRMED, INTENT_NEVER_STARTED_CERTIFIED}),
    INTENT_NEVER_STARTED_CERTIFIED: frozenset({INTENT_SEND_STARTED, INTENT_SUPERSEDED}),
    INTENT_SENT_CONFIRMED: frozenset(),
    INTENT_SUPERSEDED: frozenset(),
}

INTENT_OPERATION_CREATE = "create"
INTENT_OPERATION_UPDATE = "update"
INTENT_OPERATIONS: tuple[str, ...] = (INTENT_OPERATION_CREATE, INTENT_OPERATION_UPDATE)

# How a sent intent was confirmed: its own reply, an exact reconciled adoption, or another actor's identical end
# state ("desired state reached", not exactly-once execution; proposal §3.6).
INTENT_RESULT_KINDS: tuple[str, ...] = ("provider_reply", "reconciled_adoption", "desired_state_reached")

DOCUMENTATION_SLOT = "feature_documentation"
MARKER_PREFIX = "octryx-documentation"


def intent_marker(run_id: str, operation_id: str) -> str:
    # The marker correlates, it never authorises.
    return f"{MARKER_PREFIX}:{run_id}:{operation_id}"


def intent_transition_allowed(current: str, target: str) -> bool:
    return target in INTENT_TRANSITIONS.get(current, frozenset())


class DocumentationWriteIntent(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"run_id": "workflow_runs"}
    __tablename__ = "documentation_write_intents"
    __table_args__ = (
        CheckConstraint(in_list("state", INTENT_STATES), name="ck_documentation_write_intents_state"),
        CheckConstraint(in_list("operation", INTENT_OPERATIONS), name="ck_documentation_write_intents_operation"),
        CheckConstraint(
            "(operation = 'create' AND parent_id IS NOT NULL AND page_id IS NULL AND base_version IS NULL"
            " AND expected_version = 1)"
            " OR (operation = 'update' AND page_id IS NOT NULL AND base_version IS NOT NULL"
            " AND expected_version = base_version + 1)",
            name="ck_documentation_write_intents_target",
        ),
        CheckConstraint(
            f"state NOT IN ({', '.join(repr(s) for s in INTENT_APPROVED_STATES)})"
            " OR (decision_id IS NOT NULL AND card_hash IS NOT NULL AND body_hash IS NOT NULL"
            " AND approved_at IS NOT NULL)",
            name="ck_documentation_write_intents_approved",
        ),
        CheckConstraint(
            f"(state IN ({', '.join(repr(s) for s in INTENT_CLAIMED_STATES)})"
            " AND claimed_by IS NOT NULL AND claimed_at IS NOT NULL AND send_started_at IS NOT NULL)"
            f" OR (state NOT IN ({', '.join(repr(s) for s in INTENT_CLAIMED_STATES)})"
            " AND claimed_by IS NULL AND claimed_at IS NULL)",
            name="ck_documentation_write_intents_claim",
        ),
        CheckConstraint(
            "state <> 'sent_confirmed' OR (result_page_id IS NOT NULL AND result_version IS NOT NULL"
            " AND result_kind IS NOT NULL AND sent_confirmed_at IS NOT NULL)",
            name="ck_documentation_write_intents_result",
        ),
        CheckConstraint(
            "result_kind IS NULL OR " + in_list("result_kind", INTENT_RESULT_KINDS),
            name="ck_documentation_write_intents_result_kind",
        ),
        CheckConstraint(
            "state <> 'never_started_certified' OR (certified_by IS NOT NULL AND certified_at IS NOT NULL)",
            name="ck_documentation_write_intents_certified",
        ),
        CheckConstraint(
            "state <> 'superseded' OR superseded_at IS NOT NULL", name="ck_documentation_write_intents_superseded"
        ),
        Index(
            "uq_documentation_write_intents_active_slot",
            "run_id",
            "slot",
            unique=True,
            postgresql_where=text(f"state IN ({', '.join(repr(s) for s in INTENT_ACTIVE_STATES)})"),
            sqlite_where=text(f"state IN ({', '.join(repr(s) for s in INTENT_ACTIVE_STATES)})"),
        ),
        Index("ix_documentation_write_intents_run", "run_id", "slot", "created_at"),
        Index("ix_documentation_write_intents_state", "state", "updated_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    operation_id = Column(String(64), nullable=False, unique=True)
    marker = Column(String(255), nullable=False, unique=True)
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    slot = Column(String(64), nullable=False, default=DOCUMENTATION_SLOT)
    node_id = Column(String(128), nullable=False)
    # The pass the intent was reserved in, and the pass that last dispatched it (a retried pass keeps the intent).
    reserved_pass_key = Column(String(128), nullable=False)
    dispatch_pass_key = Column(String(128), nullable=True)
    # Approval: the (b) decision, its card hash, the documentation output hash and the approved body hash.
    decision_id = Column(String(36), ForeignKey("workflow_run_decisions.id"), nullable=True)
    card_hash = Column(String(71), nullable=True)
    output_hash = Column(String(71), nullable=True)
    body_hash = Column(String(71), nullable=True)
    connection_id = Column(String(64), nullable=False)
    instance = Column(String(500), nullable=False)
    space_id = Column(String(64), nullable=False)
    space_key = Column(String(255), nullable=True)
    parent_id = Column(String(64), nullable=True)
    page_id = Column(String(64), nullable=True)
    title = Column(String(255), nullable=False)
    operation = Column(String(10), nullable=False)
    base_version = Column(Integer, nullable=True)
    expected_version = Column(Integer, nullable=False)
    # State machine; ``state_version`` is the compare-and-set counter of every transition.
    state = Column(String(32), nullable=False, default=INTENT_RESERVED)
    state_version = Column(Integer, nullable=False, default=0, server_default="0")
    # The one claimed sender, and the stop/drift check it recorded at dispatch.
    claimed_by = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    dispatch_check = Column(JSON, nullable=True)
    # Executor certification that a claimed send never started (the only way back to a sendable state).
    certified_by = Column(String(128), nullable=True)
    certified_at = Column(DateTime, nullable=True)
    result_kind = Column(String(32), nullable=True)
    result_page_id = Column(String(64), nullable=True)
    result_version = Column(Integer, nullable=True)
    result_location = Column(JSON, nullable=True)
    result_storage_digest = Column(String(71), nullable=True)
    last_error_class = Column(String(40), nullable=True)
    last_error = Column(Text, nullable=True)
    superseded_by_id = Column(String(36), ForeignKey("documentation_write_intents.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    send_started_at = Column(DateTime, nullable=True)
    pending_reconcile_at = Column(DateTime, nullable=True)
    sent_confirmed_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


RECEIPT_ISSUED = "issued"
RECEIPT_RECORDED = "recorded"
RECEIPT_CONSUMED = "consumed"
RECEIPT_REVOKED = "revoked"
RECEIPT_EXPIRED = "expired"

RECEIPT_STATES: tuple[str, ...] = (RECEIPT_ISSUED, RECEIPT_RECORDED, RECEIPT_CONSUMED, RECEIPT_REVOKED, RECEIPT_EXPIRED)
RECEIPT_TRANSITIONS: dict[str, frozenset[str]] = {
    RECEIPT_ISSUED: frozenset({RECEIPT_RECORDED, RECEIPT_REVOKED, RECEIPT_EXPIRED}),
    RECEIPT_RECORDED: frozenset({RECEIPT_CONSUMED, RECEIPT_REVOKED, RECEIPT_EXPIRED}),
    RECEIPT_CONSUMED: frozenset(),
    RECEIPT_REVOKED: frozenset(),
    RECEIPT_EXPIRED: frozenset(),
}
RECEIPT_OUTCOME_POSITIVE = "positive"
RECEIPT_OUTCOME_NEGATIVE = "negative"
RECEIPT_OUTCOMES: tuple[str, ...] = (RECEIPT_OUTCOME_POSITIVE, RECEIPT_OUTCOME_NEGATIVE)


def receipt_transition_allowed(current: str, target: str) -> bool:
    return target in RECEIPT_TRANSITIONS.get(current, frozenset())


class DocumentationAudienceReceipt(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
    __tablename__ = "audience_receipts"
    __table_args__ = (
        CheckConstraint(in_list("state", RECEIPT_STATES), name="ck_audience_receipts_state"),
        CheckConstraint(
            "outcome IS NULL OR " + in_list("outcome", RECEIPT_OUTCOMES), name="ck_audience_receipts_outcome"
        ),
        CheckConstraint("expires_at > issued_at", name="ck_audience_receipts_expiry"),
        CheckConstraint(
            "state NOT IN ('recorded', 'consumed')"
            " OR (outcome IS NOT NULL AND recorded_at IS NOT NULL AND result_digest IS NOT NULL"
            " AND recorded_by IS NOT NULL AND recorded_by = expected_principal_id)",
            name="ck_audience_receipts_recorded",
        ),
        # Consumed exactly once, and only by the run the challenge was issued for.
        CheckConstraint(
            "(state = 'consumed' AND consumed_at IS NOT NULL AND consumed_by_run_id IS NOT NULL"
            " AND consumed_by_run_id = run_id)"
            " OR (state <> 'consumed' AND consumed_at IS NULL AND consumed_by_run_id IS NULL)",
            name="ck_audience_receipts_consumed",
        ),
        CheckConstraint("state <> 'revoked' OR revoked_at IS NOT NULL", name="ck_audience_receipts_revoked"),
        Index(
            "uq_audience_receipts_consumed_pass",
            "run_id",
            "node_id",
            "pass_key",
            unique=True,
            postgresql_where=text("state = 'consumed'"),
            sqlite_where=text("state = 'consumed'"),
        ),
        Index("ix_audience_receipts_run", "run_id", "node_id", "pass_key", "state"),
        Index("ix_audience_receipts_principal", "expected_principal_id", "state"),
        Index("ix_audience_receipts_intent", "intent_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    # Server-generated challenge identifier: an id, never a bearer secret (P must be signed in as P).
    challenge_id = Column(String(64), nullable=False, unique=True)
    # Server-owned bindings.
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(128), nullable=False)
    pass_key = Column(String(128), nullable=False)
    intent_id = Column(String(36), ForeignKey("documentation_write_intents.id"), nullable=False)
    publication_card_hash = Column(String(71), nullable=False)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    connection_id = Column(String(64), nullable=False)
    instance = Column(String(500), nullable=False)
    source_key = Column(String(255), nullable=False)
    page_id = Column(String(64), nullable=False)
    page_version = Column(Integer, nullable=False)
    revision_id = Column(String(64), nullable=False)
    revision_digest = Column(String(71), nullable=False)
    # The content assertions / query set the server derived from the confirmed contract, and its digest.
    query_set = Column(JSON, nullable=False, default=list)
    query_set_digest = Column(String(71), nullable=False)
    expected_principal_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    # Configured actor/account/role/ACL/head facts checked at issue and again at consume.
    issue_checks = Column(JSON, nullable=False, default=dict)
    consume_checks = Column(JSON, nullable=True)
    # Lifecycle; ``state_version`` is the compare-and-set counter.
    state = Column(String(16), nullable=False, default=RECEIPT_ISSUED)
    state_version = Column(Integer, nullable=False, default=0, server_default="0")
    issued_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=False)
    # Result facts of P's real retrieval
    recorded_at = Column(DateTime, nullable=True)
    recorded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    outcome = Column(String(16), nullable=True)
    hits = Column(JSON, nullable=True)
    assertion_results = Column(JSON, nullable=True)
    result_digest = Column(String(71), nullable=True)
    # Single use
    consumed_at = Column(DateTime, nullable=True)
    consumed_by_run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


__all__ = [
    "DOCUMENTATION_SLOT",
    "INTENT_ACTIVE_STATES",
    "INTENT_CLAIMED_STATES",
    "INTENT_OPERATIONS",
    "INTENT_POTENTIALLY_SENT_STATES",
    "INTENT_RESULT_KINDS",
    "INTENT_SENDABLE_STATES",
    "INTENT_STATES",
    "INTENT_TRANSITIONS",
    "RECEIPT_OUTCOMES",
    "RECEIPT_STATES",
    "RECEIPT_TRANSITIONS",
    "DocumentationAudienceReceipt",
    "DocumentationWriteIntent",
    "intent_marker",
    "intent_transition_allowed",
    "receipt_transition_allowed",
]
