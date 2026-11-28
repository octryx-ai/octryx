"""Fixed failure tokens for persisted retention outcomes. Never a message, a server code or a class name."""

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
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)

_TOKENS = (
    (KnowledgeObjectNotConfiguredError, RETENTION_FAILURE_NOT_CONFIGURED),
    (KnowledgeObjectInvalidConfigurationError, RETENTION_FAILURE_NOT_CONFIGURED),
    (KnowledgeObjectUnauthorizedError, RETENTION_FAILURE_UNAUTHORIZED),
    (KnowledgeObjectUnavailableError, RETENTION_FAILURE_UNAVAILABLE),
    (KnowledgeObjectNotFoundError, RETENTION_FAILURE_NOT_FOUND),
)


def failure_token(error: object) -> str:
    if isinstance(error, KnowledgeObjectError):
        for error_type, token in _TOKENS:
            if isinstance(error, error_type):
                return token
    return RETENTION_FAILURE_CONTRACT
