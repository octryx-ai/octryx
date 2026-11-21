"""Fixed, secret-safe outcome taxonomy of the object reconciliation slice.

One state enum the operator API and the operator CLI both map from, so an unclear outcome
becomes an explicit state instead of a silent no-op. Messages are fixed per class and the
constructors take no free text, so no object key, content address, bucket, endpoint,
credential or S3 error body can reach an HTTP payload, a console line or a log record.
"""

from __future__ import annotations

from enum import StrEnum


class RetentionState(StrEnum):
    """Stable, operator-facing outcome states of the reconciliation slice."""

    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    NEEDS_CONFIGURATION = "needs_configuration"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    CONTRACT_VIOLATION = "contract_violation"


class RetentionError(Exception):
    """Base class; ``state`` is the explicit outcome a caller must surface."""

    state: RetentionState = RetentionState.CONTRACT_VIOLATION
    default_message = "knowledge object retention request failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class RetentionRecordNotFoundError(RetentionError):
    """The Workspace, run or finding is unknown inside this Workspace's scope."""

    state = RetentionState.NOT_FOUND
    default_message = "knowledge object retention record not found"


class InvalidRetentionRequestError(RetentionError):
    """A request value is outside its validated bounds."""

    state = RetentionState.INVALID_REQUEST
    default_message = "invalid knowledge object retention request"


class RetentionNotConfiguredError(RetentionError):
    """Object storage is not configured, so there is no inventory to reconcile."""

    state = RetentionState.NEEDS_CONFIGURATION
    default_message = "knowledge object storage is not configured"


class RetentionUnauthorizedError(RetentionError):
    """The object store rejected the operator identity's inventory grant."""

    state = RetentionState.UNAUTHORIZED
    default_message = "knowledge object storage rejected the retention identity"


class RetentionUnavailableError(RetentionError):
    """A configured dependency is reachable in principle but not right now."""

    state = RetentionState.UNAVAILABLE
    default_message = "knowledge object storage is unavailable"


class RetentionContractError(RetentionError):
    """A dependency answered outside its contract, or the ledger is inconsistent."""

    state = RetentionState.CONTRACT_VIOLATION
    default_message = "knowledge object retention dependency violated its contract"
