"""The recovery vocabulary, refusal classification and audit fields of ``recovery``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ....models.project.knowledge_evidence import OUTBOX_STATE_PENDING
from ..ledger.errors import EvidenceLedgerContractError

# Operations. The two requeue tokens share one transition and differ only in how the
# decision was reached, which is worth recording: an operator's explicit request and
# an identical re-upload are not the same governance event even though they move the
# obligation the same way.
RECOVERY_OPERATION_REQUEUE = "requeue_dead_letter"
RECOVERY_OPERATION_REQUEUE_ON_REUPLOAD = "requeue_dead_letter_on_reupload"
RECOVERY_OPERATION_RETRY_NOW = "retry_now"
REQUEUE_OPERATIONS = frozenset({RECOVERY_OPERATION_REQUEUE, RECOVERY_OPERATION_REQUEUE_ON_REUPLOAD})
ALL_RECOVERY_OPERATIONS = REQUEUE_OPERATIONS | {RECOVERY_OPERATION_RETRY_NOW}

# Results. Fixed tokens, so a caller and an audit reader see the same vocabulary.
RECOVERY_RESULT_REQUEUED = "requeued"
RECOVERY_RESULT_RETRY_SCHEDULED = "retry_scheduled"
RECOVERY_RESULT_ALREADY_PENDING = "already_pending"
RECOVERY_RESULT_ALREADY_DUE = "already_due"
RECOVERY_RESULT_NOT_RECOVERABLE = "not_recoverable"
# The two results that mean the row changed, and therefore that a record was written.
CHANGED_RESULTS = frozenset({RECOVERY_RESULT_REQUEUED, RECOVERY_RESULT_RETRY_SCHEDULED})
ALL_RECOVERY_RESULTS = CHANGED_RESULTS | {
    RECOVERY_RESULT_ALREADY_PENDING,
    RECOVERY_RESULT_ALREADY_DUE,
    RECOVERY_RESULT_NOT_RECOVERABLE,
}

# The audited resource is the durable obligation, not the document.
AUDIT_RESOURCE_TYPE = "knowledge_projection_outbox"

# Bounds for the audited values. Identifiers are UUID strings and tokens come from
# the constants above, so nothing wider or outside this charset is legitimate.
_MAX_AUDIT_VALUE_CHARS = 64
# Every identifier this service accepts or records lives in a ``String(36)`` column.
_MAX_ID_CHARS = 36
_MAX_ACTOR_ROLE_CHARS = 100
_ID_CHARS = frozenset("0123456789abcdefABCDEF-")


@dataclass(frozen=True, slots=True)
class ProjectionRecovery:
    """The decision one recovery request reached, as fixed tokens only.

    ``outbox_state`` is the state the obligation is in afterwards: ``pending`` for
    the two transitions, and the observed state for a refusal — which is why a
    refusal is deterministic information rather than an opaque error.
    """

    entry_id: str
    revision_id: str
    operation: str
    previous_state: str
    result: str
    outbox_state: str

    @property
    def changed(self) -> bool:
        return self.result in CHANGED_RESULTS


@dataclass(frozen=True, slots=True)
class _Obligation:
    """The obligation as read, including the schedule value used as its CAS token."""

    entry_id: str
    state: str
    next_attempt_at: datetime
    due: bool


def _refused(obligation: _Obligation, revision_id: str, operation: str) -> ProjectionRecovery:
    """Classify a request this obligation's state does not permit.

    A repeat of a recovery that already succeeded is the idempotent answer
    (``already_pending`` / ``already_due``); ``claimed`` and ``applied`` are the
    states recovery may not touch at all.
    """
    if operation in REQUEUE_OPERATIONS:
        result = (
            RECOVERY_RESULT_ALREADY_PENDING
            if obligation.state == OUTBOX_STATE_PENDING
            else RECOVERY_RESULT_NOT_RECOVERABLE
        )
    elif obligation.state == OUTBOX_STATE_PENDING:
        result = RECOVERY_RESULT_ALREADY_DUE
    else:
        result = RECOVERY_RESULT_NOT_RECOVERABLE
    return ProjectionRecovery(
        entry_id=obligation.entry_id,
        revision_id=revision_id,
        operation=operation,
        previous_state=obligation.state,
        result=result,
        outbox_state=obligation.state,
    )


def _audit_details(recovery: ProjectionRecovery) -> dict[str, str]:
    """The closed field set of one recovery record, validated before the insert."""
    details = {
        "operation": recovery.operation,
        "outbox_entry_id": recovery.entry_id,
        "revision_id": recovery.revision_id,
        "previous_state": recovery.previous_state,
        "result": recovery.result,
    }
    for key, value in details.items():
        if type(value) is not str or not 0 < len(value) <= _MAX_AUDIT_VALUE_CHARS:
            raise EvidenceLedgerContractError()
        if key.endswith("_id") and not set(value) <= _ID_CHARS:
            # Identifiers are UUID strings; anything else would be free text.
            raise EvidenceLedgerContractError()
    return details
