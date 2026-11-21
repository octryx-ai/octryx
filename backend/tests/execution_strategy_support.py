"""Shared assertion for undecided execution strategy decisions."""


def _assert_undecided_default(decision) -> None:
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.routing_intent_source == "default"
    assert decision.routing_intent_confidence == 1.0
    assert decision.execution_strategy == "direct"
    assert decision.execution_strategy_reason == "strategy:direct_default"
    assert decision.workflow_id == ""
    assert decision.workflow_contract.get("workflow_id") in (None, "")
