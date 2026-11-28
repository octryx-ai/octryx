"""Fixed, secret-safe outcome taxonomy of the object reconciliation slice. Constructors take no free text."""

from __future__ import annotations

from enum import StrEnum


class RetentionState(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    NEEDS_CONFIGURATION = "needs_configuration"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    CONTRACT_VIOLATION = "contract_violation"


class RetentionError(Exception):
    state: RetentionState = RetentionState.CONTRACT_VIOLATION
    default_message = "knowledge object retention request failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class RetentionRecordNotFoundError(RetentionError):
    state = RetentionState.NOT_FOUND
    default_message = "knowledge object retention record not found"


class InvalidRetentionRequestError(RetentionError):
    state = RetentionState.INVALID_REQUEST
    default_message = "invalid knowledge object retention request"


class RetentionNotConfiguredError(RetentionError):
    state = RetentionState.NEEDS_CONFIGURATION
    default_message = "knowledge object storage is not configured"


class RetentionUnauthorizedError(RetentionError):
    state = RetentionState.UNAUTHORIZED
    default_message = "knowledge object storage rejected the retention identity"


class RetentionUnavailableError(RetentionError):
    state = RetentionState.UNAVAILABLE
    default_message = "knowledge object storage is unavailable"


class RetentionContractError(RetentionError):
    state = RetentionState.CONTRACT_VIOLATION
    default_message = "knowledge object retention dependency violated its contract"
