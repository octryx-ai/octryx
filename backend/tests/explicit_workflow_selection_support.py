"""Shared helpers for the test_explicit_workflow_selection_* modules."""

from __future__ import annotations

from app.services.execution_profile_service import build_execution_profile

AWS_TOPOLOGY_KEY = "aws-topology-diagram-routing"


PROMPT_WITHOUT_ROUTING_KEYWORDS = "Bitte erstelle die Uebersicht."


PROMPT_WITH_ROUTING_KEYWORDS = "Create an AWS topology architecture diagram."


def _profile_for_resolution(resolution: dict) -> object:
    return build_execution_profile(
        prompt=PROMPT_WITHOUT_ROUTING_KEYWORDS,
        requested_agent_type="diagnosis",
        effective_agent_type="chat",
        execution_strategy="direct",
        execution_strategy_reason="strategy:test",
        routing_intent="diagnosis",
        routing_reason="intent:diagnosis_default",
        routing_intent_confidence=1.0,
        routing_intent_source="policy",
        workflow_id="",
        workflow_contract={},
        workflow_routing_policy_resolution=resolution,
    )
