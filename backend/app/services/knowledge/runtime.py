"""Explicit wiring of the Evidence slice's external dependencies.

The slice needs the S3-compatible object store and the application's own PostgreSQL, which holds
the Evidence index (``evidence_index/postgres_client.py``) and the Workspace knowledge graph
(``kg_node``/``kg_edge``). Either one missing is the typed ``needs_configuration`` state — the
application still starts, the routes still answer, and nothing silently degrades to a filesystem
write or to a full-corpus Python retrieval.

The configuration mapping is passed in explicitly. The process-wide accessor
reads ``os.environ`` once and caches the assembled runtime; ``reset_evidence_runtime``
exists so a test can rebuild it.

The sandboxed parser is optional too: without it, PDF and Office uploads answer
``needs_configuration`` before anything is written, and text-native ingestion is unaffected.

The embedding space is optional: without it the lexical slice works unchanged and the
vector mode answers ``needs_configuration`` with the fixed reason kept here.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .embedding.port import EmbeddingError, EmbeddingRuntime
from .embedding.selection import build_embedder, embedding_config_from_environment
from .evidence_index.base import EvidenceIndexClient
from .ingestion.docling_client import DoclingSandboxParser, docling_config_from_environment
from .ingestion.parser_port import DocumentParser, ParserError
from .ledger.errors import EvidenceStoreNotConfiguredError, EvidenceStoreUnavailableError
from .objects import (
    KnowledgeObjectError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectStore,
    KnowledgeObjectStoreConfig,
    object_store_config_from_mapping,
)
from .rerank.selection import RerankerRuntime, reranker_from_environment
from .retrieval.index_query_store import EvidenceIndexQueryStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenceRuntime:
    """The configured dependencies of the Evidence slice, assembled once."""

    object_store: KnowledgeObjectStore
    runtime_client: EvidenceIndexClient
    query_store: EvidenceIndexQueryStore
    embedding: EmbeddingRuntime | None = None
    # Why ``embedding`` is absent: a fixed reason token for the vector mode's explicit state.
    embedding_unavailable_reason: str = "space_not_configured"
    reranker: RerankerRuntime | None = None
    # The sandboxed PDF/Office parser; absent means those uploads need configuration.
    parser: DocumentParser | None = None
    parser_unavailable_reason: str = "parser_not_configured"

    def __repr__(self) -> str:
        # Nothing about the endpoints or the bucket belongs in a log line.
        return "EvidenceRuntime(configured=True)"


def _object_config(environ: Mapping[str, str]) -> KnowledgeObjectStoreConfig:
    try:
        return object_store_config_from_mapping(environ)
    except KnowledgeObjectNotConfiguredError:
        failure: Exception = EvidenceStoreNotConfiguredError()
    except KnowledgeObjectError:
        # An invalid configuration is a deployment problem, not a transient one.
        failure = EvidenceStoreNotConfiguredError()
    raise failure


def _embedding(environ: Mapping[str, str]) -> tuple[EmbeddingRuntime | None, str]:
    """The configured embedding space, or ``None`` with the fixed reason it is absent."""
    try:
        config = embedding_config_from_environment(environ)
        return EmbeddingRuntime(space=config.space, embedder=build_embedder(config)), ""
    except EmbeddingError as error:
        logger.info("Knowledge embedding is not available: reason=%s", error.reason)
        return None, error.reason


def _reranker(environ: Mapping[str, str]) -> RerankerRuntime | None:
    try:
        return reranker_from_environment(environ)
    except EmbeddingError as error:
        logger.info("Knowledge reranker is not available: reason=%s", error.reason)
        return None


def _parser(environ: Mapping[str, str]) -> tuple[DocumentParser | None, str]:
    try:
        return DoclingSandboxParser(docling_config_from_environment(environ)), ""
    except ParserError as error:
        logger.info("Knowledge parser sandbox is not available: reason=%s", error.reason)
        return None, error.reason


def _postgres_client() -> EvidenceIndexClient:
    from .evidence_index.postgres_client import application_index_client

    client = application_index_client()
    if client is None:
        # The index tables exist on PostgreSQL only (created by the Alembic migration).
        raise EvidenceStoreNotConfiguredError()
    return client


def build_evidence_runtime(environ: Mapping[str, str]) -> EvidenceRuntime:
    """Assemble the runtime from an explicit mapping, or refuse with a typed state."""
    if not isinstance(environ, Mapping):
        raise EvidenceStoreNotConfiguredError()
    object_store = KnowledgeObjectStore(_object_config(environ))
    client = _postgres_client()
    embedding, reason = _embedding(environ)
    parser, parser_reason = _parser(environ)
    return EvidenceRuntime(
        object_store=object_store,
        runtime_client=client,
        query_store=EvidenceIndexQueryStore(client, embedding=embedding),
        embedding=embedding,
        embedding_unavailable_reason=reason or "space_not_configured",
        reranker=_reranker(environ),
        parser=parser,
        parser_unavailable_reason=parser_reason or "parser_not_configured",
    )


_RUNTIME: EvidenceRuntime | None = None
_UNCONFIGURED = False


def get_evidence_runtime() -> EvidenceRuntime:
    """The process-wide runtime; raises the typed state when unconfigured."""
    global _RUNTIME, _UNCONFIGURED
    if _RUNTIME is not None:
        return _RUNTIME
    if _UNCONFIGURED:
        raise EvidenceStoreNotConfiguredError()
    try:
        _RUNTIME = build_evidence_runtime(os.environ)
    except EvidenceStoreNotConfiguredError:
        # Remembered, so an unconfigured deployment does not re-parse per request.
        _UNCONFIGURED = True
        logger.info("Knowledge evidence runtime is not configured; routes answer needs_configuration")
        raise
    return _RUNTIME


def set_evidence_runtime(runtime: EvidenceRuntime | None) -> None:
    """Install or clear the process-wide runtime. For wiring and tests only."""
    global _RUNTIME, _UNCONFIGURED
    if runtime is not None and type(runtime) is not EvidenceRuntime:
        raise EvidenceStoreUnavailableError()
    _RUNTIME = runtime
    _UNCONFIGURED = False


def reset_evidence_runtime() -> None:
    """Forget the cached runtime so the next call re-reads the environment."""
    set_evidence_runtime(None)
