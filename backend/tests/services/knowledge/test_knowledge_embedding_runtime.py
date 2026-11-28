"""Governed embedding runtime resolution (control-plane use_case_tags)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge_embedding.provider_runtime import (
    _bedrock_client_kwargs,
    _embedding_family_for_provider,
    resolve_knowledge_embedding_runtime,
)
from app.services.knowledge_embedding.providers import KnowledgeEmbeddingProvider


@pytest.mark.asyncio
async def test_runtime_falls_back_to_env_default_when_no_embedding_target(db):
    # No runtime target is tagged "embedding" in the seeded control plane, so the
    # governed resolver falls back to the environment/local default.
    provider = await resolve_knowledge_embedding_runtime(db)
    assert provider.provider_id == "local_hash"


def test_embedding_family_maps_bedrock_and_rejects_others():
    assert _embedding_family_for_provider(SimpleNamespace(driver="bedrock_api", provider_family="aws")) == "bedrock"
    assert _embedding_family_for_provider(SimpleNamespace(driver="", provider_family="aws")) == "bedrock"
    assert _embedding_family_for_provider(SimpleNamespace(driver="openrouter_api", provider_family="openrouter")) is None
    assert _embedding_family_for_provider(SimpleNamespace(driver="copilot_api", provider_family="github")) is None


def test_bedrock_client_kwargs_maps_region_and_static_creds():
    kwargs = _bedrock_client_kwargs(
        {
            "region": "eu-central-1",
            "aws_access_key_id": "AKIA...",
            "aws_secret_access_key": "secret",
            "aws_session_token": None,
            "role_arn": "arn:aws:iam::x:role/y",
        }
    )
    assert kwargs == {"region_name": "eu-central-1", "aws_access_key_id": "AKIA...", "aws_secret_access_key": "secret"}


def test_injected_driver_is_used_by_provider():
    # The governed Bedrock path builds a driver with per-provider credentials and
    # injects it; embed_texts must use the injected driver, not the registry.
    class _FakeDriver:
        provider_id = "bedrock"
        model = "m"
        version = "v"

        def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
            return [[1.0, 2.0, 3.0] for _ in texts]

    provider = KnowledgeEmbeddingProvider(
        provider_id="bedrock",
        model="amazon.titan-embed-text-v2:0",
        version="bedrock:amazon.titan-embed-text-v2:0",
        configured_provider="bedrock",
        configured_model="amazon.titan-embed-text-v2:0",
        driver=_FakeDriver(),
    )
    assert provider.embed_text("hello") == [1.0, 2.0, 3.0]
