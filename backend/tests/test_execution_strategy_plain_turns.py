"""Execution strategy defaults: plain prompts, continuation words, removed hints and operations prompts stay plain governed turns unless explicitly routed."""

import pytest

from app.services import execution_strategy_service as strategy_service
from app.services.execution_strategy_service import resolve_execution_strategy
from tests.execution_strategy_support import _assert_undecided_default


def test_resolve_execution_strategy_routes_simple_chat_prompt_to_direct() -> None:
    decision = resolve_execution_strategy(
        prompt="Say hello in one short sentence.",
        requested_agent_type="diagnosis",
    )

    assert decision.execution_strategy == "direct"
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.effective_agent_type == "chat"
    assert decision.workflow_id == ""


def test_resolve_execution_strategy_default_does_not_classify_plain_coding_prompt() -> None:
    """Explicit-first default: a plain "fix this bug" prompt runs as a normal governed turn."""
    decision = resolve_execution_strategy(
        prompt="fix this bug",
        requested_agent_type="diagnosis",
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.effective_agent_type == "chat"
    assert decision.workflow_id == ""


@pytest.mark.parametrize("prompt", ["continue", "weiter", "retry", "Please carry on.", "next", "proceed"])
def test_resolve_execution_strategy_continuation_words_decide_nothing(prompt) -> None:
    """Without an explicit input of this turn, a continuation word is a plain turn."""
    decision = strategy_service.resolve_execution_strategy(prompt=prompt, requested_agent_type="diagnosis")

    _assert_undecided_default(decision)
    assert decision.effective_agent_type == "chat"


@pytest.mark.parametrize(
    "removed_input",
    [
        {"routing_intent_hint": "coding"},
        {"routing_intent_source": "llm"},
        {"routing_reason_hint": "llm:stale"},
        {"routing_intent_confidence": 0.99},
    ],
)
def test_resolve_execution_strategy_has_no_stored_hint_inputs(removed_input) -> None:
    """Routing hints stored by earlier turns cannot even be passed in."""
    with pytest.raises(TypeError):
        strategy_service.resolve_execution_strategy(
            prompt="continue", requested_agent_type="diagnosis", **removed_input
        )


def test_removed_llm_hint_machinery_stays_removed() -> None:
    assert not hasattr(strategy_service, "_ROUTING_HINT_REUSE_PATTERN")
    assert not hasattr(strategy_service, "ROUTING_INTENT_SOURCE_LLM")
    assert not hasattr(strategy_service, "resolve_chat_intent_hint")
    assert not hasattr(strategy_service, "classify_chat_intent_with_llm")


def test_resolve_execution_strategy_default_keeps_implicit_coding_prompt_as_plain_turn() -> None:
    """No explicit mode, no policy, no LLM decision: coding keywords no longer promote the turn."""
    decision = resolve_execution_strategy(
        prompt=(
            "In a small Python codebase, implement a build_project_budget_warning_banner helper "
            "and include focused pytest tests."
        ),
        requested_agent_type="diagnosis",
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.effective_agent_type == "chat"
    assert decision.workflow_id == ""


def test_resolve_execution_strategy_neutral_start_never_flips_the_mode() -> None:
    """Neutral start: with no explicit input a turn stays chat;
    no classification preloads or narrows the toolset or flips the mode."""
    for prompt in ("Erstelle mir ein Diagramm der AWS Infrastruktur.", "Bitte fasse das kurz zusammen."):
        decision = strategy_service.resolve_execution_strategy(prompt=prompt, requested_agent_type="diagnosis")

        _assert_undecided_default(decision)
        assert decision.effective_agent_type == "chat"


def test_resolve_execution_strategy_default_does_not_auto_promote_java_spring_migration() -> None:
    decision = resolve_execution_strategy(
        prompt=(
            "Migriere acme-orders-access-proxy zu Java 25 und Spring Boot 4.0.3 "
            "und aktualisiere auch die README documentation."
        ),
        requested_agent_type="diagnosis",
        agent_type_explicit=False,
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.effective_agent_type == "chat"
    assert decision.workflow_id == ""


def test_resolve_execution_strategy_default_routes_operations_prompt_as_plain_turn() -> None:
    decision = resolve_execution_strategy(
        prompt="Deploy the current release candidate and verify the rollout status.",
        requested_agent_type="diagnosis",
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.effective_agent_type == "chat"
