"""Explicit fail-closed errors of the Knowledge retrieval contract.

Every error carries a stable ``state`` so callers can turn it into an explicit
product state instead of a silent empty result. Messages are fixed per class:
the constructors take no message, so no caller, store, or adapter can place
query text, identifiers, SQL, or store internals into a public error.
"""

from __future__ import annotations

from enum import StrEnum

# Must equal the ``RetrievalMode`` values (pinned by a unit test); kept literal
# here because ``contracts`` depends on this module.
INDEX_MODES = frozenset({"lexical", "vector", "graph"})


class RetrievalFailureState(StrEnum):
    """Stable, product-facing failure states of a retrieval request."""

    DENIED = "denied"
    INVALID_REQUEST = "invalid_request"
    NEEDS_CONFIGURATION = "needs_configuration"
    UNAVAILABLE = "unavailable"
    STORE_CONTRACT_VIOLATION = "store_contract_violation"


class KnowledgeRetrievalError(Exception):
    """Base class; ``state`` is the explicit outcome a caller must surface."""

    state: RetrievalFailureState = RetrievalFailureState.DENIED
    default_message = "knowledge retrieval failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class WorkspaceScopeError(KnowledgeRetrievalError):
    """No usable Workspace scope: retrieval is denied, never widened."""

    state = RetrievalFailureState.DENIED
    default_message = "a valid workspace is required"


class WorkspaceRequiredError(WorkspaceScopeError):
    """The Workspace is absent (None or empty)."""

    default_message = "workspace is required"


class InvalidWorkspaceError(WorkspaceScopeError):
    """The Workspace is present but not a canonical, non-nil UUID."""

    default_message = "workspace must be a canonical non-nil UUID"


class InvalidRetrievalRequestError(KnowledgeRetrievalError, ValueError):
    """A request or contract value is outside its validated bounds."""

    state = RetrievalFailureState.INVALID_REQUEST
    default_message = "invalid knowledge retrieval request"


class KnowledgeStoreNotConfiguredError(KnowledgeRetrievalError):
    """No usable Knowledge query store is configured for this deployment."""

    state = RetrievalFailureState.NEEDS_CONFIGURATION
    default_message = "knowledge query store is not configured"


class KnowledgeIndexUnavailableError(KnowledgeRetrievalError):
    """The index backing one retrieval mode cannot serve the request."""

    state = RetrievalFailureState.UNAVAILABLE
    default_message = "knowledge index is unavailable"

    def __init__(self, mode: object) -> None:
        # Exact mode values only: no str() coercion of arbitrary objects.
        if not isinstance(mode, str) or mode not in INDEX_MODES:
            raise ValueError("unknown retrieval mode")
        super().__init__()
        self.mode = str(mode)


class KnowledgeStoreContractError(KnowledgeRetrievalError):
    """A store failed or returned data that violates the retrieval contract."""

    state = RetrievalFailureState.STORE_CONTRACT_VIOLATION
    default_message = "knowledge query store violated the retrieval contract"
