"""A runtime target's temperature: the model catalog's value (``LLMModel.temperature``), or never send.

- ``services/control_plane/runtime_temperature``: the effective value says what will actually be sent and why,
  from the target's ``accepts_temperature`` (never send = False) and its model's catalog value.
- The value reaches the payloads: direct Bedrock ``inferenceConfig`` and Graphiti's ``chat`` options
  (the LiteLLM gateway body is asserted in ``tests/model_gateway/test_litellm_target_temperature``).

No live model, network or AWS call.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.engine.runtime._engine_runtime_fallback import _runtime_client_kwargs_for_turn
from app.agent.providers.bedrock import BedrockClient
from app.agent.providers.sampling_capabilities import gateway_temperature, sampling_temperature
from app.models import ControlPlaneRuntimeTarget, LLMModel
from app.services.content_security.model_call_scope import session_call
from app.services.control_plane import runtime_temperature as rt
from app.services.control_plane.selection_policy import build_runtime_selection_payload
from app.services.knowledge.temporal.graphiti_llm import GovernedGraphitiLLM
from tests.runtime_target_temperature_value_support import ACCEPTING, REJECTING

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

MESSAGES = [{"role": "user", "content": "hi"}]


def _target(model_id: str = ACCEPTING, *, accepts: bool | None = None):
    return SimpleNamespace(model_id=model_id, accepts_temperature=accepts)


# --- payload wiring --------------------------------------------------------------------------------


class _Converse:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": "ok"}]}}, "usage": {}}


def _bedrock(monkeypatch, **kwargs: Any) -> tuple[BedrockClient, _Converse]:
    monkeypatch.setattr(BedrockClient, "_list_foundation_model_summaries", lambda self: [])
    client = BedrockClient(region="eu-central-1", **kwargs)
    client._client = _Converse()
    return client, client._client


class _Recording:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **_runtime: Any) -> Any:
        recording = self

        class _Client:
            async def chat(self, **options: Any) -> dict[str, Any]:
                recording.calls.append(options)
                return {"content": json.dumps({"ok": True}), "usage": {}}

        return _Client()


# --- the sampling rule ---------------------------------------------------------------------------


def test_the_target_value_wins_unless_the_model_gets_no_temperature():
    assert sampling_temperature(ACCEPTING, 0.3, target_value=0.9) == 0.9
    assert sampling_temperature(ACCEPTING, None, target_value=0.0) == 0.0
    assert sampling_temperature(ACCEPTING, 0.3) == 0.3
    assert sampling_temperature(REJECTING, 0.3, target_value=0.9) is None
    assert sampling_temperature(ACCEPTING, 0.3, override=False, target_value=0.9) is None
    assert sampling_temperature(REJECTING, None, override=True, target_value=1.5) == 1.5


def test_the_gateway_rule_adds_no_default_and_honours_never_send():
    assert gateway_temperature(None) is None
    assert gateway_temperature(0.3) == 0.3
    assert gateway_temperature(0.3, target_value=1.2) == 1.2
    assert gateway_temperature(0.3, override=False, target_value=1.2) is None
    assert gateway_temperature(None, override=True) is None


# --- effective value ---------------------------------------------------------------------------------


def test_the_effective_value_says_what_is_sent_and_why():
    def effective(target, value=None, driver="bedrock_api"):
        result = rt.effective_temperature(target, value, driver=driver)
        return result["mode"], result["value"], result["reason"]

    assert effective(_target(), 0.7) == ("sent", 0.7, "model_value")
    assert effective(_target()) == ("sent", 0.0, "deterministic_default")
    assert effective(_target(), driver="litellm_gateway") == ("model_default", None, "provider_default")
    assert effective(_target(), 1.1, "litellm_gateway") == ("sent", 1.1, "model_value")
    assert effective(_target(accepts=False), 0.7) == ("not_sent", None, "target_never_send")
    assert effective(_target(REJECTING), 0.7) == ("not_sent", None, "model_rejects_temperature")
    assert effective(_target(REJECTING, accepts=True)) == ("sent", 0.0, "deterministic_default")
    assert effective(_target(), 0.7, "openrouter_api") == ("driver_managed", None, "driver_not_governed")
    assert rt.effective_temperature(_target(), 0.7, driver="bedrock_api")["label"] == "0.7 (set for this model)"


async def test_the_bedrock_inference_config_carries_the_target_value(monkeypatch):
    client, converse = _bedrock(monkeypatch, target_temperature=0.7)
    await client.chat(MESSAGES, model=ACCEPTING)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096, "temperature": 0.7}
    await client.chat(MESSAGES, model=ACCEPTING, temperature=0.2, max_tokens=50)
    assert converse.calls[-1]["inferenceConfig"] == {"maxTokens": 50, "temperature": 0.7}

    never, never_converse = _bedrock(monkeypatch, accepts_temperature=False, target_temperature=0.7)
    await never.chat(MESSAGES, model=ACCEPTING, temperature=0.2)
    assert never_converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096}

    default, default_converse = _bedrock(monkeypatch)
    await default.chat(MESSAGES, model=ACCEPTING)
    assert default_converse.calls[-1]["inferenceConfig"] == {"maxTokens": 4096, "temperature": 0.0}


async def test_graph_extraction_sends_the_target_value(monkeypatch):
    recording = _Recording()
    monkeypatch.setattr("app.agent.providers.get_provider", recording)
    messages = [SimpleNamespace(role="user", content="x")]
    runtime = {"provider_name": "bedrock", "model": ACCEPTING, "target_temperature": 1.3}

    await GovernedGraphitiLLM([runtime], scope=session_call(None), temperature=0.2)._generate_response(messages)
    assert recording.calls[-1]["temperature"] == 1.3
    await GovernedGraphitiLLM([{**runtime, "accepts_temperature": False}], scope=session_call(None))._generate_response(messages)
    assert "temperature" not in recording.calls[-1]


@pytest.mark.parametrize("value", [None, 0.0, 1.4])
def test_the_selection_payload_and_the_factory_hand_the_models_value_to_the_clients(value, monkeypatch):
    from app.agent.providers import get_provider

    target = ControlPlaneRuntimeTarget(id="t", provider_id="p", model_id=ACCEPTING, priority=1)
    model = LLMModel(provider_id="p", model_id=ACCEPTING, temperature=value)
    payload = build_runtime_selection_payload(
        client_kwargs={"provider_name": "bedrock", "driver": "bedrock_api"},
        provider=None,
        target=target,
        model=model,
        model_id=ACCEPTING,
        priority=1,
        use_case_tags=[],
        max_tokens_per_request=None,
        request_timeout_seconds=None,
    )
    assert payload["target_temperature"] == value
    kwargs = _runtime_client_kwargs_for_turn(payload, reasoning_effort=None)
    assert kwargs["target_temperature"] == value
    assert get_provider(**kwargs).target_temperature == value

    built: dict[str, Any] = {}
    monkeypatch.setattr(
        "app.agent.providers.litellm_gateway.LiteLLMGatewayClient", lambda **options: built.update(options)
    )
    get_provider(driver="litellm_gateway", accepts_temperature=False, target_temperature=value)
    assert (built["accepts_temperature"], built["target_temperature"]) == (False, value)
