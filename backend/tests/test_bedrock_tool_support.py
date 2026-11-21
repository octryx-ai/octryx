"""Bedrock catalog records documented Converse tool support, and unknown stays unknown."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.agent.providers.bedrock_capabilities import bedrock_tool_support


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("anthropic.claude-sonnet-4-5-20250929-v1:0", True),
        ("eu.anthropic.claude-haiku-4-5-20251001-v1:0", True),
        ("anthropic.claude-3-5-sonnet-20240620-v1:0", True),
        ("anthropic.claude-v2:1", False),
        ("anthropic.claude-instant-v1", False),
        ("amazon.nova-2-lite-v1:0", True),
        ("amazon.nova-pro-v1:0", True),
        ("amazon.titan-text-express-v1", False),
        ("meta.llama3-1-70b-instruct-v1:0", True),
        ("meta.llama3-8b-instruct-v1:0", False),
        ("mistral.mistral-large-2407-v1:0", True),
        ("mistral.devstral-2-123b", None),
        ("deepseek.r1-v1:0", None),
        ("", None),
    ],
)
def test_documented_families_only(model_id: str, expected: bool | None) -> None:
    assert bedrock_tool_support(model_id) is expected


def test_list_models_carries_the_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.providers.bedrock import BedrockClient

    class _Client:
        def list_foundation_models(self):
            return {
                "modelSummaries": [
                    {"modelId": "anthropic.claude-sonnet-4-5-20250929-v1:0", "outputModalities": ["TEXT"]},
                    {"modelId": "mistral.devstral-2-123b", "outputModalities": ["TEXT"]},
                ]
            }

    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: _Client())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    provider = BedrockClient.__new__(BedrockClient)
    monkeypatch.setattr(provider, "_aws_client_kwargs", lambda: {}, raising=False)

    models = asyncio.run(provider.list_models())

    assert {m["id"]: m["supports_tools"] for m in models} == {
        "anthropic.claude-sonnet-4-5-20250929-v1:0": True,
        "mistral.devstral-2-123b": None,
    }
