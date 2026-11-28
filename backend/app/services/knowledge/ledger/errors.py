"""Fixed, secret-safe outcome taxonomy of the Workspace Knowledge Evidence slice. Constructors take no free text, so
nothing internal reaches a payload or a log."""

from __future__ import annotations

from enum import StrEnum

# The single rendered text for an inaccessible Workspace. It is both the
# exception message and the HTTP detail, so the two can never diverge and give
# a caller a way to tell 'unknown' from 'not yours'.
WORKSPACE_NOT_FOUND_DETAIL = "Workspace not found"


class EvidenceLedgerState(StrEnum):
    OK = "ok"
    DENIED = "denied"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    NEEDS_CONFIGURATION = "needs_configuration"
    # An empty Workspace is not a misconfiguration: no source yet, or sources whose projection is pending.
    NO_SOURCES = "no_sources"
    PROJECTION_PENDING = "projection_pending"
    UNAVAILABLE = "unavailable"
    CONTRACT_VIOLATION = "contract_violation"
    LIMIT_EXCEEDED = "limit_exceeded"


class EvidenceLedgerError(Exception):
    state: EvidenceLedgerState = EvidenceLedgerState.CONTRACT_VIOLATION
    default_message = "knowledge evidence request failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class WorkspaceNotAccessibleError(EvidenceLedgerError):
    # One state for "does not exist" and "not yours", so no caller can enumerate Workspaces.
    state = EvidenceLedgerState.NOT_FOUND
    default_message = WORKSPACE_NOT_FOUND_DETAIL


class EmbeddingSpaceDeniedError(EvidenceLedgerError):
    state = EvidenceLedgerState.DENIED
    default_message = "the embedding space is not admitted for this workspace"


class EvidenceRecordNotFoundError(EvidenceLedgerError):
    state = EvidenceLedgerState.NOT_FOUND
    default_message = "knowledge evidence record not found"


class InvalidEvidenceRequestError(EvidenceLedgerError):
    state = EvidenceLedgerState.INVALID_REQUEST
    default_message = "invalid knowledge evidence request"


class UnsupportedMediaTypeError(EvidenceLedgerError):
    state = EvidenceLedgerState.UNSUPPORTED_MEDIA_TYPE
    default_message = "media type is not supported"


class EvidenceParserNotConfiguredError(EvidenceLedgerError):
    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the sandboxed document parser is not configured"


class EvidenceGraphNotConfiguredError(EvidenceLedgerError):
    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the knowledge graph is not configured"


class EvidenceStoreNotConfiguredError(EvidenceLedgerError):
    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "knowledge evidence storage is not configured"


class EvidenceNoSourcesError(EvidenceLedgerError):
    state = EvidenceLedgerState.NO_SOURCES
    default_message = "the workspace has no knowledge sources yet"


class EvidenceProjectionPendingError(EvidenceLedgerError):
    state = EvidenceLedgerState.PROJECTION_PENDING
    default_message = "the workspace knowledge projection is pending"


class EvidenceStoreUnavailableError(EvidenceLedgerError):
    state = EvidenceLedgerState.UNAVAILABLE
    default_message = "knowledge evidence storage is unavailable"


class EvidencePayloadTooLargeError(EvidenceLedgerError):
    state = EvidenceLedgerState.LIMIT_EXCEEDED
    default_message = "knowledge evidence payload exceeds the supported byte-size bound"


class EvidenceSpanLimitExceededError(EvidenceLedgerError):
    # A capacity limit, not malformed input: ``limit_exceeded`` (413), not ``invalid_request``.
    state = EvidenceLedgerState.LIMIT_EXCEEDED
    default_message = "knowledge evidence document exceeds the supported span count for one revision"


class EvidenceLedgerContractError(EvidenceLedgerError):
    state = EvidenceLedgerState.CONTRACT_VIOLATION
    default_message = "knowledge evidence dependency violated its contract"
