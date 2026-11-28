"""Explicit fail-closed errors of the Knowledge retrieval contract. Constructors take no message."""

from __future__ import annotations

from enum import StrEnum

# Must equal the ``RetrievalMode`` values (pinned by a unit test); kept literal
# here because ``contracts`` depends on this module.
INDEX_MODES = frozenset({"lexical", "vector", "graph"})


class RetrievalFailureState(StrEnum):
    DENIED = "denied"
    INVALID_REQUEST = "invalid_request"
    NEEDS_CONFIGURATION = "needs_configuration"
    UNAVAILABLE = "unavailable"
    STORE_CONTRACT_VIOLATION = "store_contract_violation"


class KnowledgeRetrievalError(Exception):
    state: RetrievalFailureState = RetrievalFailureState.DENIED
    default_message = "knowledge retrieval failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class WorkspaceScopeError(KnowledgeRetrievalError):
    # Retrieval is denied, never widened.
    state = RetrievalFailureState.DENIED
    default_message = "a valid workspace is required"


class WorkspaceRequiredError(WorkspaceScopeError):
    default_message = "workspace is required"


class InvalidWorkspaceError(WorkspaceScopeError):
    default_message = "workspace must be a canonical non-nil UUID"


class InvalidRetrievalRequestError(KnowledgeRetrievalError, ValueError):
    state = RetrievalFailureState.INVALID_REQUEST
    default_message = "invalid knowledge retrieval request"


class KnowledgeStoreNotConfiguredError(KnowledgeRetrievalError):
    state = RetrievalFailureState.NEEDS_CONFIGURATION
    default_message = "knowledge query store is not configured"


class KnowledgeIndexUnavailableError(KnowledgeRetrievalError):
    state = RetrievalFailureState.UNAVAILABLE
    default_message = "knowledge index is unavailable"

    def __init__(self, mode: object) -> None:
        # Exact mode values only: no str() coercion of arbitrary objects.
        if not isinstance(mode, str) or mode not in INDEX_MODES:
            raise ValueError("unknown retrieval mode")
        super().__init__()
        self.mode = str(mode)


class KnowledgeStoreContractError(KnowledgeRetrievalError):
    state = RetrievalFailureState.STORE_CONTRACT_VIOLATION
    default_message = "knowledge query store violated the retrieval contract"
