"""Fixed, secret-safe outcome taxonomy of the Workspace Knowledge Evidence slice.

One state enum the API and the tool both map from, so an unclear outcome becomes
an explicit product state (``denied``, ``needs_configuration``, ...) instead of a
silent empty result. Messages are fixed per class and the constructors take no
free text, so no object key, database name, statement, credential, or server
body can reach an HTTP payload, a tool result, or a log line.
"""

from __future__ import annotations

from enum import StrEnum

# The single rendered text for an inaccessible Workspace. It is both the
# exception message and the HTTP detail, so the two can never diverge and give
# a caller a way to tell 'unknown' from 'not yours'.
WORKSPACE_NOT_FOUND_DETAIL = "Workspace not found"


class EvidenceLedgerState(StrEnum):
    """Stable, product-facing outcome states of the Evidence ledger slice."""

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
    """Base class; ``state`` is the explicit outcome a caller must surface."""

    state: EvidenceLedgerState = EvidenceLedgerState.CONTRACT_VIOLATION
    default_message = "knowledge evidence request failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class WorkspaceNotAccessibleError(EvidenceLedgerError):
    """The Workspace is unknown to this caller.

    Deliberately one state for "does not exist" and "exists but not yours": the
    API renders both as the same 404 body, so no caller can enumerate
    Workspaces it has no access to.
    """

    state = EvidenceLedgerState.NOT_FOUND
    default_message = WORKSPACE_NOT_FOUND_DETAIL


class EmbeddingSpaceDeniedError(EvidenceLedgerError):
    """The Workspace's data classification may not reach the Instance's remote embedding space."""

    state = EvidenceLedgerState.DENIED
    default_message = "the embedding space is not admitted for this workspace"


class EvidenceRecordNotFoundError(EvidenceLedgerError):
    """A source, revision, span, or citation is unknown inside this Workspace."""

    state = EvidenceLedgerState.NOT_FOUND
    default_message = "knowledge evidence record not found"


class InvalidEvidenceRequestError(EvidenceLedgerError):
    """A request value is outside its validated bounds."""

    state = EvidenceLedgerState.INVALID_REQUEST
    default_message = "invalid knowledge evidence request"


class UnsupportedMediaTypeError(EvidenceLedgerError):
    """The declared or sniffed type is neither text-native nor one the parser sandbox owns.

    Raised before any object write: an image, an archive, or bytes that do not match their
    declared type.
    """

    state = EvidenceLedgerState.UNSUPPORTED_MEDIA_TYPE
    default_message = "media type is not supported"


class EvidenceParserNotConfiguredError(EvidenceLedgerError):
    """A PDF or Office upload, but the Instance has no sandboxed parser.

    Raised before any object write, like an unsupported media type, but it is a configuration
    state: the same upload succeeds once the Docling sandbox is configured.
    """

    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the sandboxed document parser is not configured"


class EvidenceGraphNotConfiguredError(EvidenceLedgerError):
    """The knowledge graph needs its Bolt endpoint and the Instance's embedding space."""

    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the knowledge graph is not configured"


class EvidenceStoreNotConfiguredError(EvidenceLedgerError):
    """Object storage or the Workspace projection is not configured."""

    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "knowledge evidence storage is not configured"


class EvidenceNoSourcesError(EvidenceLedgerError):
    """The Workspace has no Knowledge source yet: ingestion never ran, so there is nothing to search.

    Not a misconfiguration: the instance is fine, and the answer is to add a source.
    """

    state = EvidenceLedgerState.NO_SOURCES
    default_message = "the workspace has no knowledge sources yet"


class EvidenceProjectionPendingError(EvidenceLedgerError):
    """The Workspace has sources, but their search projection is not current yet."""

    state = EvidenceLedgerState.PROJECTION_PENDING
    default_message = "the workspace knowledge projection is pending"


class EvidenceStoreUnavailableError(EvidenceLedgerError):
    """A configured dependency is reachable in principle but not right now."""

    state = EvidenceLedgerState.UNAVAILABLE
    default_message = "knowledge evidence storage is unavailable"


class EvidencePayloadTooLargeError(EvidenceLedgerError):
    """The uploaded payload exceeds the bounded byte size this slice accepts."""

    state = EvidenceLedgerState.LIMIT_EXCEEDED
    default_message = "knowledge evidence payload exceeds the supported byte-size bound"


class EvidenceSpanLimitExceededError(EvidenceLedgerError):
    """The document splits into more evidence spans than one revision may hold.

    A capacity limit, not malformed input: the bytes are valid text-native content
    that this slice refuses to project because one revision's span count is
    bounded. It is therefore ``limit_exceeded`` (HTTP 413) with an actionable
    message, not ``invalid_request``.
    """

    state = EvidenceLedgerState.LIMIT_EXCEEDED
    default_message = "knowledge evidence document exceeds the supported span count for one revision"


class EvidenceLedgerContractError(EvidenceLedgerError):
    """A dependency answered outside its contract, or the ledger is inconsistent."""

    state = EvidenceLedgerState.CONTRACT_VIOLATION
    default_message = "knowledge evidence dependency violated its contract"
