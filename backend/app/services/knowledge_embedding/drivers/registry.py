"""Resolve a configured (provider, model) into a concrete embedding driver.

Driver instances are cached: real backends load a model or open a client, which
is expensive, so we keep one per (provider, model, version). Failures are not
cached — a misconfigured provider re-attempts on the next call and keeps raising
loudly.
"""

from __future__ import annotations

from functools import lru_cache

from .base import (
    FAMILY_BEDROCK,
    FAMILY_IN_PROCESS,
    FAMILY_LOCAL_HASH,
    BaseEmbeddingDriver,
    EmbeddingConfigurationError,
    resolve_driver_family,
)
from .bedrock import BedrockEmbeddingDriver
from .hash_driver import HashEmbeddingDriver
from .in_process import InProcessEmbeddingDriver


@lru_cache(maxsize=32)
def build_embedding_driver(provider_id: str, model: str, version: str) -> BaseEmbeddingDriver:
    family = resolve_driver_family(provider_id)
    if family == FAMILY_LOCAL_HASH:
        return HashEmbeddingDriver(model=model, version=version)
    if family == FAMILY_IN_PROCESS:
        return InProcessEmbeddingDriver(model=model, version=version)
    if family == FAMILY_BEDROCK:
        return BedrockEmbeddingDriver(model=model, version=version)
    raise EmbeddingConfigurationError(f"No embedding driver for family '{family}'.")
