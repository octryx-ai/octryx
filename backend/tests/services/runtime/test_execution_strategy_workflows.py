"""Execution strategy workflow routing: a workflow run phase's contract and intent, governance resolutions, bounded child runs and coding turns."""

from app.services import execution_strategy_service as strategy_service
from app.services.execution_strategy_service import resolve_execution_strategy


def _phase_resolution(workflow_id: str, **contract: object) -> dict:
    return {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_id": workflow_id,
        "workflow_class": workflow_id,
        "workflow_contract": {"workflow_id": workflow_id, "workflow_class": workflow_id, **contract},
    }


def test_resolve_execution_strategy_uses_the_phase_workflow_contract() -> None:
    decision = resolve_execution_strategy(
        prompt="What do we know about the release process?",
        requested_agent_type="diagnosis",
        workflow_routing_policy_resolution=_phase_resolution("knowledge_request"),
    )

    assert decision.workflow_id == "knowledge_request"
    assert decision.workflow_contract["workflow_id"] == "knowledge_request"


def test_resolve_execution_strategy_uses_the_phase_intent() -> None:
    # No keyword classifier: the phase intent decides.
    decision = strategy_service.resolve_execution_strategy(
        prompt="Implement code changes, but the phase is a knowledge request.",
        requested_agent_type="diagnosis",
        workflow_routing_policy_resolution=_phase_resolution("knowledge_request", routing_intent="knowledge"),
    )

    assert decision.routing_intent == "knowledge"
    assert decision.routing_reason == "routing_policy:routing_intent"
    assert decision.routing_intent_source == "policy"
    assert decision.workflow_id == "knowledge_request"


def test_resolve_execution_strategy_phase_resolution_still_decides_with_a_continuation_word() -> None:
    decision = strategy_service.resolve_execution_strategy(
        prompt="continue",
        requested_agent_type="diagnosis",
        support_request_signature=True,
        workflow_routing_policy_resolution=_phase_resolution("knowledge_request", routing_intent="knowledge"),
    )

    assert decision.routing_intent == "knowledge"
    assert decision.routing_reason == "routing_policy:routing_intent"
    assert decision.routing_intent_source == "policy"
    assert decision.workflow_id == "knowledge_request"


def test_resolve_execution_strategy_attaches_resolution_for_workflow_governance() -> None:
    decision = resolve_execution_strategy(
        prompt="welche informationen haben wir über aws RDS",
        requested_agent_type="diagnosis",
        workflow_routing_policy_resolution={
            "source": "workflow_routing_policy",
            "status": "unmatched",
            "workflow_id": None,
            "workflow_contract": None,
        },
    )

    assert decision.workflow_id == ""
    assert decision.workflow_contract == {}
    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"


def test_resolve_execution_strategy_never_latches_workflows_from_prompt_text() -> None:
    for prompt in (
        "Research ticketing API integration and produce a concise evidence-backed brief on "
        "benefits, risks, use cases, and rollout guidance.",
        "Create a 10-slide presentation about enterprise LLM adoption risks and benefits.",
        "welche informationen haben wir über aws RDS",
        "was ist der letzte realese wo ausgeführt wurde?",
        "What can you tell me about Report Builder from knowledge?",
    ):
        decision = resolve_execution_strategy(
            prompt=prompt,
            requested_agent_type="diagnosis",
        )
        assert decision.execution_strategy == "direct", prompt
        assert decision.execution_strategy_reason == "strategy:direct_default", prompt
        assert decision.workflow_id == "", prompt
        assert decision.workflow_contract == {}, prompt


def test_resolve_execution_strategy_disables_workflow_contracts_for_bounded_child_runs() -> None:
    decision = resolve_execution_strategy(
        prompt="What do we know about the release process?",
        requested_agent_type="documentation",
        agent_type_explicit=True,
        allow_workflow_contracts=False,
        workflow_routing_policy_resolution=_phase_resolution("knowledge_request"),
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_workflow_disabled"
    assert decision.workflow_id == ""
    assert decision.workflow_contract == {}


def test_resolve_execution_strategy_keeps_an_explicit_coding_phase_direct() -> None:
    decision = resolve_execution_strategy(
        prompt=(
            "Continue the Acme Orders Java 25 / Spring Boot 4.0.3 coding migration. "
            "Update the Maven pom, implement source changes, run focused tests, fix "
            "compile/test issues, and document remaining runtime or observability gaps "
            "only after the code work."
        ),
        requested_agent_type="coding",
        agent_type_explicit=True,
        workflow_routing_policy_resolution=_phase_resolution("coding_change_tdd"),
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_coding"
    assert decision.routing_intent == "coding"
    assert decision.routing_reason == "explicit_mode:coding"
    assert decision.effective_agent_type == "coding"
    assert decision.workflow_id == "coding_change_tdd"
    assert decision.workflow_contract["workflow_id"] == "coding_change_tdd"


def test_resolve_execution_strategy_keeps_an_implicit_coding_phase_direct() -> None:
    # The requested coding mode still drives the coding capability (and the
    # TDD contract); only the keyword-derived routing intent is gone.
    decision = resolve_execution_strategy(
        prompt=(
            "Continue the existing Acme Orders Java 25 / Spring Boot 4.0.3 migration. "
            "Update code and run Maven validation; do not claim completion from POM-only edits."
        ),
        requested_agent_type="coding",
        agent_type_explicit=False,
        workflow_routing_policy_resolution=_phase_resolution("coding_change_tdd"),
    )

    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_coding"
    assert decision.effective_agent_type == "coding"
    assert decision.workflow_id == "coding_change_tdd"
    assert decision.workflow_contract["workflow_id"] == "coding_change_tdd"
