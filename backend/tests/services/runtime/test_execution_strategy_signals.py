"""Execution strategy signals: current-evidence signatures, explicit mode labels, support request signatures and specialist targets."""

import pytest

from app.services import execution_strategy_intent
from app.services import execution_strategy_service as strategy_service
from app.services.execution_strategy_service import resolve_execution_strategy
from tests.services.runtime.execution_strategy_support import _assert_undecided_default


def test_resolve_execution_strategy_signature_decides_only_with_current_evidence() -> None:
    evidence_prompt = "The simulation failed with a SQLServerException and a stack trace after a read timed out."
    decision = strategy_service.resolve_execution_strategy(
        prompt=evidence_prompt, requested_agent_type="diagnosis", support_request_signature=True
    )

    assert decision.routing_intent == "support_request"
    assert decision.routing_reason == "intent:support_request_signature"
    assert decision.routing_intent_source == "signature"
    assert decision.routing_intent_confidence == 1.0
    _assert_undecided_default(
        strategy_service.resolve_execution_strategy(prompt=evidence_prompt, requested_agent_type="diagnosis")
    )
    _assert_undecided_default(
        strategy_service.resolve_execution_strategy(
            prompt="weiter bitte", requested_agent_type="diagnosis", support_request_signature=True
        )
    )


def test_resolve_execution_strategy_labels_an_explicit_mode_decision() -> None:
    decision = strategy_service.resolve_execution_strategy(
        prompt="Add a unit test for the parser.", requested_agent_type="coding", agent_type_explicit=True
    )

    assert decision.routing_intent == "coding"
    assert decision.routing_reason == "explicit_mode:coding"
    assert decision.routing_intent_source == "explicit"


@pytest.mark.asyncio
async def test_support_request_signature_applies_only_to_error_evidence() -> None:
    assert (
        await execution_strategy_intent.support_request_signature_applies(
            "Create a concise Word report about ticketing API integration risks."
        )
        is False
    )
    assert await execution_strategy_intent.support_request_signature_applies("") is False
    assert (
        await execution_strategy_intent.support_request_signature_applies(
            "The simulation failed with a SQLServerException and a stack trace after a read timed out."
        )
        is True
    )


@pytest.mark.asyncio
async def test_support_request_signature_never_resolves_runtimes_or_builds_a_provider(db, monkeypatch) -> None:
    import app.agent.providers as providers_module
    import app.services.control_plane_service as control_plane_service

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("routing must not resolve runtimes or build a provider")

    monkeypatch.setattr(providers_module, "get_provider", _forbidden)
    monkeypatch.setattr(control_plane_service, "resolve_control_plane_runtimes", _forbidden)

    evidence = "I am seeing an error message: the request read timed out with a stack trace."
    assert await execution_strategy_intent.support_request_signature_applies(evidence, db=db) is True
    assert await execution_strategy_intent.support_request_signature_applies("Reply with exactly READY-1", db=db) is False


def test_resolve_execution_strategy_keeps_explicit_targets_on_specialist_path() -> None:
    decision = resolve_execution_strategy(
        prompt="Create a concise delivery plan for the next release.",
        requested_agent_type="change",
        agent_id="agent-123",
    )

    assert decision.execution_strategy == "specialist"
    assert decision.execution_strategy_reason == "strategy:explicit_target"
    assert decision.effective_agent_type == "change"
