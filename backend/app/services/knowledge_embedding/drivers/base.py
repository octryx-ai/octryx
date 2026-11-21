"""Embedding driver contract and provider-family resolution.

A driver turns text into a real embedding vector. The knowledge base supports
three families:

- ``local_hash`` — deterministic SHA256 token-hash vectors. Explicit, non-semantic,
  offline/dev only. Selected only when configured as ``local_hash`` — never as a
  silent fallback.
- ``in_process`` — a real embedding model loaded in-process (fastembed /
  sentence-transformers). The on-prem option.
- ``bedrock`` — AWS Bedrock embedding models (Titan / Cohere).

When a real provider is configured but cannot produce embeddings, drivers raise
``EmbeddingConfigurationError`` loudly instead of degrading to hash vectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingConfigurationError(RuntimeError):
    """A configured embedding provider cannot produce embeddings.

    Deliberately loud: the platform never silently substitutes a non-semantic
    hash embedding when a real provider was requested.
    """


FAMILY_LOCAL_HASH = "local_hash"
FAMILY_IN_PROCESS = "in_process"
FAMILY_BEDROCK = "bedrock"

_FAMILY_ALIASES: dict[str, set[str]] = {
    FAMILY_LOCAL_HASH: {"hash", "hash_embedding", "hash_embedding_fallback", "local", "local_hash"},
    FAMILY_IN_PROCESS: {
        "in_process",
        "inprocess",
        "fastembed",
        "sentence_transformers",
        "local_model",
        "huggingface",
        "hf",
    },
    FAMILY_BEDROCK: {"bedrock", "aws", "aws_bedrock", "amazon_bedrock", "titan", "cohere"},
}

DEFAULT_IN_PROCESS_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_BEDROCK_MODEL = "amazon.titan-embed-text-v2:0"

# Best-effort expected dimensions for status/metadata. The authoritative
# dimension is the length of the vector a driver actually returns.
_EXPECTED_DIMENSION: dict[tuple[str, str | None], int] = {
    (FAMILY_LOCAL_HASH, None): 96,
    (FAMILY_IN_PROCESS, "BAAI/bge-small-en-v1.5"): 384,
    (FAMILY_IN_PROCESS, "BAAI/bge-base-en-v1.5"): 768,
    (FAMILY_IN_PROCESS, "BAAI/bge-m3"): 1024,
    (FAMILY_IN_PROCESS, "intfloat/multilingual-e5-large"): 1024,
    (FAMILY_IN_PROCESS, "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"): 768,
    (FAMILY_BEDROCK, "amazon.titan-embed-text-v2:0"): 1024,
    (FAMILY_BEDROCK, "amazon.titan-embed-text-v1"): 1536,
    (FAMILY_BEDROCK, "cohere.embed-english-v3"): 1024,
    (FAMILY_BEDROCK, "cohere.embed-multilingual-v3"): 1024,
}


def normalize_provider_id(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def resolve_driver_family(provider_id: str) -> str:
    normalized = normalize_provider_id(provider_id)
    for family, aliases in _FAMILY_ALIASES.items():
        if normalized == family or normalized in aliases:
            return family
    raise EmbeddingConfigurationError(
        f"Unknown embedding provider '{provider_id}'. "
        f"Configure one of: {FAMILY_LOCAL_HASH}, {FAMILY_IN_PROCESS}, {FAMILY_BEDROCK}."
    )


def expected_dimension(family: str, model: str | None) -> int | None:
    if family == FAMILY_LOCAL_HASH:
        return _EXPECTED_DIMENSION[(FAMILY_LOCAL_HASH, None)]
    return _EXPECTED_DIMENSION.get((family, model))


class BaseEmbeddingDriver(ABC):
    """Turns texts into embedding vectors. Implementations must be deterministic
    for a fixed (provider, model) so stored vectors round-trip at query time."""

    provider_id: str
    model: str
    version: str

    @abstractmethod
    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """Return one vector per input text. ``is_query`` marks retrieval-time
        queries — models with asymmetric encodings (e.g. E5's query:/passage:
        prefixes) encode them differently from indexed passages. Raises
        EmbeddingConfigurationError if the backend is unavailable or fails."""
