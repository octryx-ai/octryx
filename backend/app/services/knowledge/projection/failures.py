"""Map a projection dependency failure onto one fixed, persistable token. No server body, record id, statement or file
name is persisted."""

from __future__ import annotations

from ....models.project.knowledge_evidence import (
    PROJECTION_FAILURE_CONTRACT,
    PROJECTION_FAILURE_EMBEDDING_CONTRACT,
    PROJECTION_FAILURE_EMBEDDING_DENIED,
    PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED,
    PROJECTION_FAILURE_EMBEDDING_UNAVAILABLE,
    PROJECTION_FAILURE_GRAPH_CONTRACT,
    PROJECTION_FAILURE_GRAPH_MODEL_UNAVAILABLE,
    PROJECTION_FAILURE_GRAPH_NOT_CONFIGURED,
    PROJECTION_FAILURE_GRAPH_UNAVAILABLE,
    PROJECTION_FAILURE_LEDGER,
    PROJECTION_FAILURE_PARSER_CONTRACT,
    PROJECTION_FAILURE_PARSER_NOT_CONFIGURED,
    PROJECTION_FAILURE_PARSER_REFUSED,
    PROJECTION_FAILURE_PARSER_UNAVAILABLE,
    PROJECTION_FAILURE_UNAVAILABLE,
)
from ..embedding.port import EmbeddingError, EmbeddingState
from ..evidence_index.errors import EvidenceIndexContractError, EvidenceIndexError
from ..ingestion.parser_port import ParserError, ParserState
from ..ledger.errors import EvidenceLedgerError
from ..temporal.errors import GraphModelUnavailableError, GraphNotConfiguredError, GraphStoreError, GraphStoreState

_EMBEDDING_FAILURE_BY_STATE = {
    EmbeddingState.NEEDS_CONFIGURATION: PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED,
    EmbeddingState.DENIED: PROJECTION_FAILURE_EMBEDDING_DENIED,
    EmbeddingState.UNAVAILABLE: PROJECTION_FAILURE_EMBEDDING_UNAVAILABLE,
    EmbeddingState.CONTRACT_VIOLATION: PROJECTION_FAILURE_EMBEDDING_CONTRACT,
    EmbeddingState.LIMIT_EXCEEDED: PROJECTION_FAILURE_EMBEDDING_CONTRACT,
}
_PARSER_FAILURE_BY_STATE = {
    ParserState.NEEDS_CONFIGURATION: PROJECTION_FAILURE_PARSER_NOT_CONFIGURED,
    ParserState.UNAVAILABLE: PROJECTION_FAILURE_PARSER_UNAVAILABLE,
    ParserState.REFUSED: PROJECTION_FAILURE_PARSER_REFUSED,
    ParserState.CONTRACT_VIOLATION: PROJECTION_FAILURE_PARSER_CONTRACT,
}


def failure_token(error: BaseException) -> str:
    if isinstance(error, EmbeddingError):
        return _EMBEDDING_FAILURE_BY_STATE[error.state]
    if isinstance(error, ParserError):
        return _PARSER_FAILURE_BY_STATE[error.state]
    if isinstance(error, GraphNotConfiguredError):
        return PROJECTION_FAILURE_GRAPH_NOT_CONFIGURED
    if isinstance(error, GraphModelUnavailableError):
        return PROJECTION_FAILURE_GRAPH_MODEL_UNAVAILABLE
    if isinstance(error, GraphStoreError):
        return PROJECTION_FAILURE_GRAPH_CONTRACT if error.state == GraphStoreState.CONTRACT_VIOLATION else (
            PROJECTION_FAILURE_GRAPH_UNAVAILABLE
        )
    if isinstance(error, TimeoutError):
        return PROJECTION_FAILURE_UNAVAILABLE
    if isinstance(error, EvidenceIndexContractError):
        return PROJECTION_FAILURE_CONTRACT
    if isinstance(error, EvidenceIndexError):
        return PROJECTION_FAILURE_UNAVAILABLE
    if isinstance(error, EvidenceLedgerError):
        return PROJECTION_FAILURE_LEDGER
    return PROJECTION_FAILURE_UNAVAILABLE


__all__ = ["failure_token"]
