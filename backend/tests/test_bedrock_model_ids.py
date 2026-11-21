"""The direct Bedrock client's request contract.

- A bare model id becomes a cross-region inference profile id only when the Bedrock model catalog
  (``ListFoundationModels`` ``inferenceTypesSupported``) does not list it as on-demand only; an
  on-demand-only model (e.g. Qwen) and any ARN are used exactly as configured.
- ``inferenceConfig`` keeps the engine deterministic: temperature 0 unless the caller sets another,
  and none for a model that rejects an explicit temperature (Claude 5 family, ``sampling_capabilities``)
  or whose runtime target overrides the catalog.

The catalog is a stub; no AWS call is made.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.providers import bedrock_model_ids
from app.agent.providers.bedrock import BedrockClient
from app.agent.providers.bedrock_model_ids import resolve_bedrock_model_id

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

QWEN = "qwen.qwen3-32b-v1:0"
CLAUDE = "anthropic.claude-sonnet-4-5-20250929-v1:0"
NOVA = "amazon.nova-pro-v1:0"
CLAUDE_OPUS_5_5 = "anthropic.claude-opus-5-5"
CLAUDE_SONNET_5 = "eu.anthropic.claude-sonnet-5-v1:0"
CATALOG = [
    {"modelId": QWEN, "inferenceTypesSupported": ["ON_DEMAND"]},
    {"modelId": CLAUDE, "inferenceTypesSupported": ["INFERENCE_PROFILE"]},
    {"modelId": NOVA, "inferenceTypesSupported": ["ON_DEMAND", "INFERENCE_PROFILE"]},
]
MESSAGES = [{"role": "user", "content": "hi"}]


class _Converse:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": "ok"}]}}, "usage": {}}


def _client(monkeypatch, catalog: list[dict[str, Any]] | None = None) -> tuple[BedrockClient, _Converse, list[int]]:
    reads: list[int] = []

    def summaries(self) -> list[dict[str, Any]]:
        reads.append(1)
        return list(CATALOG if catalog is None else catalog)

    monkeypatch.setattr(BedrockClient, "_list_foundation_model_summaries", summaries)
    client = BedrockClient(region="eu-central-1")
    converse = _Converse()
    client._client = converse
    return client, converse, reads


async def test_an_on_demand_only_model_is_called_as_configured_and_profile_models_keep_the_prefix(monkeypatch):
    client, converse, reads = _client(monkeypatch)
    for model in (QWEN, CLAUDE, NOVA):
        await client.chat(MESSAGES, model=model)
    assert [call["modelId"] for call in converse.calls] == [QWEN, f"eu.{CLAUDE}", f"eu.{NOVA}"]
    # One catalog read per region, then cached.
    assert len(reads) == 1


async def test_an_arn_or_a_profile_id_is_never_prefixed_and_never_needs_the_catalog(monkeypatch):
    client, converse, reads = _client(monkeypatch)
    arn = "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/eu.anthropic.claude-opus-5-5"
    imported = "arn:aws:bedrock:eu-central-1:123456789012:imported-model/abc"
    for model in (arn, imported, f"global.{CLAUDE}"):
        await client.chat(MESSAGES, model=model)
    assert [call["modelId"] for call in converse.calls] == [arn, imported, f"global.{CLAUDE}"]
    assert reads == []
    assert resolve_bedrock_model_id(imported, region="eu-central-1", inference_types=frozenset()) == imported


async def test_an_unknown_or_unreadable_catalog_keeps_the_existing_prefix(monkeypatch):
    client, converse, _reads = _client(monkeypatch, catalog=[])
    await client.chat(MESSAGES, model=QWEN)
    assert converse.calls[-1]["modelId"] == f"eu.{QWEN}"

    bedrock_model_ids.clear_catalog_cache()

    def unreadable(self):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(BedrockClient, "_list_foundation_model_summaries", unreadable)
    await client.chat(MESSAGES, model=QWEN)
    assert converse.calls[-1]["modelId"] == f"eu.{QWEN}"


async def test_inference_config_defaults_to_temperature_zero_and_keeps_an_explicit_one(monkeypatch):
    client, converse, _reads = _client(monkeypatch)
    await client.chat(MESSAGES, model=CLAUDE)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096, "temperature": 0.0}

    await client.chat(MESSAGES, model=CLAUDE, temperature=0.3, max_tokens=100)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 100, "temperature": 0.3}


async def test_a_claude_5_model_gets_no_temperature_even_when_one_is_requested(monkeypatch):
    client, converse, _reads = _client(monkeypatch)
    for model in (CLAUDE_OPUS_5_5, CLAUDE_SONNET_5):
        await client.chat(MESSAGES, model=model)
        assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096}
        await client.chat(MESSAGES, model=model, temperature=0.3)
        assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096}


async def test_the_runtime_target_override_beats_the_catalog(monkeypatch):
    client, converse, _reads = _client(monkeypatch)
    client.accepts_temperature = False
    await client.chat(MESSAGES, model=CLAUDE)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096}

    client.accepts_temperature = True
    await client.chat(MESSAGES, model=CLAUDE_SONNET_5)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096, "temperature": 0.0}


def test_the_factory_hands_the_target_override_to_the_bedrock_client():
    from app.agent.providers import get_provider

    assert get_provider(provider_name="bedrock", driver="bedrock_api", accepts_temperature=False).accepts_temperature is False
    assert get_provider(provider_name="bedrock", driver="bedrock_api").accepts_temperature is None
