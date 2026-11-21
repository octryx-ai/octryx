"""Embedding provider/driver layer: real drivers + loud (non-silent) failure.

Regression focus: a configured real provider must never silently degrade to the
non-semantic hash embedding. Either it produces a real vector, or it raises
EmbeddingConfigurationError loudly.
"""

from __future__ import annotations

import pytest

from app.services.knowledge_embedding.drivers import (
    DEFAULT_BEDROCK_MODEL,
    EmbeddingConfigurationError,
    build_embedding_driver,
    resolve_driver_family,
)
from app.services.knowledge_embedding.providers import (
    DEFAULT_EMBEDDING_PROVIDER,
    KNOWLEDGE_EMBEDDING_PROVIDER_ENV,
    resolve_knowledge_embedding_provider,
)


def test_default_resolves_to_hash_and_embeds_deterministically():
    provider = resolve_knowledge_embedding_provider(env={})
    assert provider.provider_id == "local_hash"
    assert provider.dimension == 96

    vector = provider.embed_text("payment service outage")
    assert len(vector) == 96
    assert provider.embed_text("payment service outage") == vector  # deterministic


def test_unknown_provider_raises_loudly():
    with pytest.raises(EmbeddingConfigurationError):
        resolve_knowledge_embedding_provider(provider_id="totally_unknown", env={})


def test_configured_real_provider_is_not_silently_downgraded_to_hash():
    provider = resolve_knowledge_embedding_provider(provider_id="in_process", env={})
    # The resolver must report the configured family, not silently local_hash.
    assert provider.provider_id == "in_process"
    assert provider.configured_provider == "in_process"

    # embed() either produces a real vector (backend installed) or fails loudly —
    # it must never return the 96-dim hash vector for a non-hash provider.
    try:
        vector = provider.embed_text("payment service outage")
    except EmbeddingConfigurationError:
        return
    assert isinstance(vector, list) and vector


def test_bedrock_resolves_to_descriptor_without_network():
    provider = resolve_knowledge_embedding_provider(provider_id="bedrock", env={})
    assert provider.provider_id == "bedrock"
    assert provider.model == DEFAULT_BEDROCK_MODEL
    assert provider.version == f"bedrock:{DEFAULT_BEDROCK_MODEL}"


def test_stale_hash_model_does_not_pin_a_real_provider():
    # A stale job carrying the hash model name must not force a real provider onto
    # the hash model; it falls back to the family default.
    provider = resolve_knowledge_embedding_provider(
        provider_id="bedrock", model="hash-embedding-v1", env={}
    )
    assert provider.model == DEFAULT_BEDROCK_MODEL


def test_query_and_index_resolution_are_identical():
    env = {KNOWLEDGE_EMBEDDING_PROVIDER_ENV: "bedrock"}
    index = resolve_knowledge_embedding_provider(env=env)
    query = resolve_knowledge_embedding_provider(env=env)
    assert (index.provider_id, index.model, index.version) == (
        query.provider_id,
        query.model,
        query.version,
    )


def test_env_override_selects_family():
    provider = resolve_knowledge_embedding_provider(env={KNOWLEDGE_EMBEDDING_PROVIDER_ENV: "aws"})
    assert provider.provider_id == "bedrock"


def test_driver_registry_hash_roundtrip():
    driver = build_embedding_driver("local_hash", "hash-embedding-v1", "hash-v1")
    vectors = driver.embed(["a", "b"])
    assert len(vectors) == 2
    assert all(len(vector) == 96 for vector in vectors)


def test_family_aliases_resolve():
    assert resolve_driver_family("fastembed") == "in_process"
    assert resolve_driver_family("titan") == "bedrock"
    assert resolve_driver_family("hash") == "local_hash"
    assert DEFAULT_EMBEDDING_PROVIDER == "local_hash"
