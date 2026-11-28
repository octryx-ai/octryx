"""Capabilities are published and tool requests admitted only after probe evidence, a failing catalog probe is a typed sync error, and temperature is sent only when a caller sets it."""

from __future__ import annotations

import json

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_CAPABILITY_NOT_PROVEN
from tests.model_gateway.conftest import ALIAS, MESSAGES, MODEL_GROUP, TOOLS, VIRTUAL_KEY, FakeLiteLLMGateway

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


async def test_capabilities_are_published_only_after_probe_evidence(gateway, build_gateway_client) -> None:
    unproven_gateway = FakeLiteLLMGateway(catalog={"data": [{"id": MODEL_GROUP}]})

    proven_catalog = await build_gateway_client(gateway).list_models()
    unproven_catalog = await build_gateway_client(unproven_gateway).list_models()

    assert proven_catalog[0]["id"] == ALIAS
    assert proven_catalog[0]["supports_tools"] is True
    assert proven_catalog[0]["supports_vision"] is False
    assert proven_catalog[0]["context_length"] == 128000
    assert proven_catalog[0]["cost_contract"] == {
        "source": "catalog_pricing",
        "input_per_million_usd": 1.0,
        "output_per_million_usd": 2.0,
    }
    assert unproven_catalog[0]["supports_tools"] is False


async def test_tool_request_without_probe_evidence_is_refused_before_dispatch(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(catalog={"data": [{"id": MODEL_GROUP}]})
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS, tools=TOOLS)

    assert excinfo.value.gateway_state == GATEWAY_STATE_CAPABILITY_NOT_PROVEN
    assert excinfo.value.denial_reason == "capability_without_probe_evidence"
    assert gateway.chat_requests == []


async def test_reasoning_the_alias_does_not_declare_is_left_out_not_refused(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(catalog={"data": [{"id": MODEL_GROUP, "model_info": {"supports_reasoning": True}}]})
    client = build_gateway_client(gateway)

    await client.chat(MESSAGES, model=ALIAS, reasoning_effort="high")

    (request,) = gateway.chat_requests
    assert "reasoning_effort" not in json.loads(request.content)


async def test_catalog_probe_failure_is_a_typed_sync_error(build_gateway_client) -> None:
    from app.services.provider.model_sync import ModelCatalogSyncError

    gateway = FakeLiteLLMGateway(catalog_status=401, catalog={"error": {"code": "invalid_api_key"}})
    client = build_gateway_client(gateway)

    with pytest.raises(ModelCatalogSyncError) as excinfo:
        await client.list_models()

    assert excinfo.value.sync_state == "auth_denied"
    assert VIRTUAL_KEY not in str(excinfo.value)


async def test_temperature_is_sent_only_when_a_caller_sets_it(gateway, build_gateway_client) -> None:
    # Opus 5.5 and Sonnet 5 on Bedrock reject any temperature but their default, so the client never
    # adds one on its own (the upstream answers "`temperature` is deprecated for this model").
    import json

    client = build_gateway_client(gateway)
    await client.chat(MESSAGES, model=ALIAS)
    assert "temperature" not in json.loads(gateway.chat_requests[-1].content)

    await client.chat(MESSAGES, model=ALIAS, temperature=0.3)
    assert json.loads(gateway.chat_requests[-1].content)["temperature"] == 0.3
