"""A runtime target's temperature: the model catalog's value or never send, and that value reaching the
Bedrock and Graphiti payloads (no live model, network or AWS call)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.providers.sampling_capabilities import gateway_temperature, sampling_temperature
from app.agent.runtime.runtime_fallback import _runtime_client_kwargs_for_turn
from app.models import ControlPlaneRuntimeTarget, LLMModel
from app.services.content_security.model_call_scope import session_call
from app.services.control_plane import runtime_temperature as rt
from app.services.control_plane.selection_policy import build_runtime_selection_payload
from app.services.knowledge.temporal.graphiti_llm import GovernedGraphitiLLM
from tests.runtime_target_temperature_value_support import ACCEPTING, REJECTING

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def _target(model_id: str = ACCEPTING, *, accepts: bool | None = None):
    return SimpleNamespace(model_id=model_id, accepts_temperature=accepts)


# --- payload wiring --------------------------------------------------------------------------------


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
    def effective(target, value=None, driver="litellm_gateway"):
        result = rt.effective_temperature(target, value, driver=driver)
        return result["mode"], result["value"], result["reason"]

    assert effective(_target(), 0.7) == ("sent", 0.7, "model_value")
    assert effective(_target()) == ("model_default", None, "provider_default")
    assert effective(_target(accepts=False), 0.7) == ("not_sent", None, "target_never_send")
    assert effective(_target(REJECTING), 0.7) == ("not_sent", None, "model_rejects_temperature")
    assert effective(_target(REJECTING, accepts=True), 1.1) == ("sent", 1.1, "model_value")
    assert effective(_target(), 0.7, "") == ("driver_managed", None, "driver_not_governed")
    assert rt.effective_temperature(_target(), 0.7, driver="litellm_gateway")["label"] == "0.7 (set for this model)"


async def test_graph_extraction_sends_the_target_value(monkeypatch):
    recording = _Recording()
    monkeypatch.setattr("app.agent.providers.get_provider", recording)
    messages = [SimpleNamespace(role="user", content="x")]
    runtime = {"provider_name": "litellm_gateway", "model": ACCEPTING, "target_temperature": 1.3}

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
        client_kwargs={"provider_name": "litellm_gateway", "driver": "litellm_gateway"},
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
    kwargs = _runtime_client_kwargs_for_turn(payload)
    assert kwargs["target_temperature"] == value

    built: dict[str, Any] = {}
    monkeypatch.setattr(
        "app.agent.providers.litellm_gateway.LiteLLMGatewayClient", lambda **options: built.update(options)
    )
    get_provider(**kwargs)
    assert built["target_temperature"] == value
    get_provider(driver="litellm_gateway", accepts_temperature=False, target_temperature=value)
    assert (built["accepts_temperature"], built["target_temperature"]) == (False, value)
