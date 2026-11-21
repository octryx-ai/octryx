"""Embedding drivers: hash (dev), in-process (fastembed/ST), Bedrock (AWS)."""

from .base import (
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_IN_PROCESS_MODEL,
    FAMILY_BEDROCK,
    FAMILY_IN_PROCESS,
    FAMILY_LOCAL_HASH,
    BaseEmbeddingDriver,
    EmbeddingConfigurationError,
    expected_dimension,
    normalize_provider_id,
    resolve_driver_family,
)
from .registry import build_embedding_driver

__all__ = [
    "DEFAULT_BEDROCK_MODEL",
    "DEFAULT_IN_PROCESS_MODEL",
    "FAMILY_BEDROCK",
    "FAMILY_IN_PROCESS",
    "FAMILY_LOCAL_HASH",
    "BaseEmbeddingDriver",
    "EmbeddingConfigurationError",
    "build_embedding_driver",
    "expected_dimension",
    "normalize_provider_id",
    "resolve_driver_family",
]
