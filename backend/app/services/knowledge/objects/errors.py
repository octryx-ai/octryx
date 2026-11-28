"""Fixed, secret-safe failure taxonomy of the Knowledge object boundary. There is no filesystem fallback state on
purpose."""

from __future__ import annotations

from enum import StrEnum


class KnowledgeObjectState(StrEnum):
    """Stable, distinguishable outcome states of the object boundary."""

    READY = "ready"
    NEEDS_CONFIGURATION = "needs_configuration"
    INVALID_CONFIGURATION = "invalid_configuration"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    OUTSIDE_PARTITION = "outside_partition"
    INTEGRITY_VIOLATION = "integrity_violation"
    LIMIT_EXCEEDED = "limit_exceeded"
    CONTRACT_VIOLATION = "contract_violation"


class KnowledgeObjectOperation(StrEnum):
    """The fixed operations of the object boundary, split by owner: the split is the privilege boundary."""

    CONFIGURATION = "configuration"
    PUT_OBJECT = "put_object"
    GET_OBJECT = "get_object"
    LIST_OBJECTS = "list_objects"


class KnowledgeObjectError(Exception):
    """Base class; ``state`` is the explicit outcome a caller must surface."""

    state: KnowledgeObjectState = KnowledgeObjectState.UNAVAILABLE
    default_message = "knowledge object storage failed"

    def __init__(self, operation: KnowledgeObjectOperation | None = None) -> None:
        # Exact enum members only: no str() coercion of arbitrary objects.
        if operation is not None and type(operation) is not KnowledgeObjectOperation:
            raise TypeError("operation must be a KnowledgeObjectOperation")
        super().__init__(self.default_message)
        self.operation = operation


class KnowledgeObjectNotConfiguredError(KnowledgeObjectError):
    """No object store is configured; the boundary never uses a local path."""

    state = KnowledgeObjectState.NEEDS_CONFIGURATION
    default_message = "knowledge object storage is not configured"


class KnowledgeObjectInvalidConfigurationError(KnowledgeObjectError):
    """A configured endpoint, bucket, region, or prefix violates the rules."""

    state = KnowledgeObjectState.INVALID_CONFIGURATION
    default_message = "knowledge object storage configuration is invalid"


class KnowledgeObjectUnavailableError(KnowledgeObjectError):
    """The endpoint is unreachable, timed out, or failed server-side."""

    state = KnowledgeObjectState.UNAVAILABLE
    default_message = "knowledge object storage is unavailable"


class KnowledgeObjectUnauthorizedError(KnowledgeObjectError):
    """The endpoint rejected the credential or the bucket is not accessible."""

    state = KnowledgeObjectState.UNAUTHORIZED
    default_message = "knowledge object storage rejected the credential"


class KnowledgeObjectNotFoundError(KnowledgeObjectError):
    """The object does not exist under the caller's Workspace prefix."""

    state = KnowledgeObjectState.NOT_FOUND
    default_message = "knowledge object does not exist"


class KnowledgeObjectOutsidePartitionError(KnowledgeObjectNotFoundError):
    """A persisted key does not lie in the caller's Workspace partition under the configured prefix."""

    state = KnowledgeObjectState.OUTSIDE_PARTITION
    default_message = "knowledge object key is outside the workspace partition"


class KnowledgeObjectIntegrityError(KnowledgeObjectError):
    """Stored bytes did not match the content digest they are addressed by."""

    state = KnowledgeObjectState.INTEGRITY_VIOLATION
    default_message = "knowledge object failed its content digest check"


class KnowledgeObjectTooLargeError(KnowledgeObjectError):
    """The payload exceeds the bounded object size this boundary accepts."""

    state = KnowledgeObjectState.LIMIT_EXCEEDED
    default_message = "knowledge object exceeds the supported size bound"


class KnowledgeObjectContractError(KnowledgeObjectError):
    """The endpoint answered outside the expected S3 contract."""

    state = KnowledgeObjectState.CONTRACT_VIOLATION
    default_message = "knowledge object storage response violated the expected contract"
