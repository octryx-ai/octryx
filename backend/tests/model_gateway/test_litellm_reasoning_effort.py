"""The gateway body carries a thinking level as LiteLLM's ``reasoning_effort`` (live S3.2 follow-up).

Live: every Opus 5.5 turn with thinking "light" got HTTP 400 "reasoning: Extra inputs are not permitted" from Bedrock
(the Responses-style ``reasoning`` object passed through LiteLLM unchanged) and silently fell back to Haiku. LiteLLM's
chat-completions parameter is ``reasoning_effort``; without a thinking level nothing is sent.
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.model_gateway.conftest import ALIAS, DEFAULT_CATALOG, MODEL_GROUP, FakeLiteLLMGateway, gateway_config

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

MESSAGES = [{"role": "user", "content": "hi"}]


def _reasoning_gateway() -> tuple[FakeLiteLLMGateway, dict]:
    catalog = copy.deepcopy(DEFAULT_CATALOG)
    catalog["data"][0]["model_info"]["supports_reasoning"] = True
    config = gateway_config()
    config["litellm_gateway"]["aliases"][ALIAS]["capabilities"] = {"tools": True, "reasoning": True}
    return FakeLiteLLMGateway(catalog=catalog), config


async def test_a_thinking_level_is_sent_as_reasoning_effort(build_gateway_client) -> None:
    gateway, config = _reasoning_gateway()
    client = build_gateway_client(gateway, config_json=config)
    await client.chat(MESSAGES, model=ALIAS, reasoning_effort="low")
    sent = json.loads(gateway.chat_requests[-1].content)
    assert sent["reasoning_effort"] == "low" and "reasoning" not in sent
    assert sent["model"] == MODEL_GROUP


async def test_no_thinking_level_sends_no_reasoning_field(build_gateway_client) -> None:
    gateway, config = _reasoning_gateway()
    client = build_gateway_client(gateway, config_json=config)
    await client.chat(MESSAGES, model=ALIAS)
    sent = json.loads(gateway.chat_requests[-1].content)
    assert "reasoning_effort" not in sent and "reasoning" not in sent
