"""Fixed failure tokens for persisted retention outcomes.

The object boundary's errors already carry no server text, but their *classes* are a code
contract, not a database value. This maps one to the other so a run or a finding records one
of ``ALL_RETENTION_FAILURES`` and never a message, a code from the server or a class name.
"""

from __future__ import annotations

from ....models.project.knowledge_object_retention import (
    RETENTION_FAILURE_CONTRACT,
    RETENTION_FAILURE_NOT_CONFIGURED,
    RETENTION_FAILURE_NOT_FOUND,
    RETENTION_FAILURE_UNAUTHORIZED,
    RETENTION_FAILURE_UNAVAILABLE,
)
from ..objects import (
    KnowledgeObjectError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)

_TOKENS = (
    (KnowledgeObjectNotConfiguredError, RETENTION_FAILURE_NOT_CONFIGURED),
    (KnowledgeObjectUnauthorizedError, RETENTION_FAILURE_UNAUTHORIZED),
    (KnowledgeObjectUnavailableError, RETENTION_FAILURE_UNAVAILABLE),
    (KnowledgeObjectNotFoundError, RETENTION_FAILURE_NOT_FOUND),
)


def failure_token(error: object) -> str:
    """The persisted token for one object-boundary failure; unknown means contract violation."""
    if isinstance(error, KnowledgeObjectError):
        for error_type, token in _TOKENS:
            if isinstance(error, error_type):
                return token
    return RETENTION_FAILURE_CONTRACT
