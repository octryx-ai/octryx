"""Canonical package surface for knowledge embeddings: the governed provider runtime and scoring."""

from .drivers import EmbeddingConfigurationError
from .provider_runtime import resolve_knowledge_embedding_runtime
from .providers import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_VERSION,
    KNOWLEDGE_EMBEDDING_MODEL_ENV,
    KNOWLEDGE_EMBEDDING_PROVIDER_ENV,
    KnowledgeEmbeddingProvider,
    resolve_knowledge_embedding_provider,
)
from .scoring import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    _tokenize,
    build_embedding_from_text,
    compute_semantic_similarity,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_EMBEDDING_VERSION",
    "EMBEDDING_DIMENSION",
    "KNOWLEDGE_EMBEDDING_MODEL_ENV",
    "KNOWLEDGE_EMBEDDING_PROVIDER_ENV",
    "KnowledgeEmbeddingProvider",
    "_tokenize",
    "build_embedding_from_text",
    "compute_semantic_similarity",
    "EmbeddingConfigurationError",
    "resolve_knowledge_embedding_provider",
    "resolve_knowledge_embedding_runtime",
]
