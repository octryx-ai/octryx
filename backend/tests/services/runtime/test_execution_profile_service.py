"""Tests for explicit execution profile metadata."""

from __future__ import annotations

from app.services.execution_profile_service import EXECUTION_PROFILE_VERSION, build_execution_profile


def _build_profile(**overrides):
    params = {
        "prompt": "What is the current status?",
        "requested_agent_type": "chat",
        "effective_agent_type": "chat",
        "execution_strategy": "direct",
        "execution_strategy_reason": "strategy:direct_default",
        "routing_intent": "diagnosis",
        "routing_reason": "intent:diagnosis_default",
        "routing_intent_confidence": 0.4,
        "routing_intent_source": "default",
        "workflow_id": "",
        "workflow_contract": {},
    }
    params.update(overrides)
    return build_execution_profile(**params).to_metadata()


def test_direct_chat_profile_is_allowed_and_versioned():
    profile = _build_profile()

    assert profile["version"] == EXECUTION_PROFILE_VERSION
    assert profile["status"] == "allowed"
    assert profile["profile_id"] == "direct_chat_safe"
    assert profile["decision_source"] == "direct_chat_safe"
    assert profile["llm_router"]["status"] == "not_used"


def test_workflow_run_phase_profile_records_the_run_as_decision_source():
    profile = _build_profile(
        prompt="Fix the failing login test",
        routing_intent="coding",
        routing_reason="workflow_run:phase",
        routing_intent_confidence=1.0,
        routing_intent_source="policy",
        workflow_id="coding_change_tdd",
        workflow_contract={"workflow_id": "coding_change_tdd"},
        workflow_routing_policy_resolution={
            "source": "db",
            "status": "matched",
            "selection_source": "workflow_run",
            "policy_id": "phase-1",
            "policy_version_id": "version-1",
            "matched_group_id": "group-1",
            "workflow_id": "coding_change_tdd",
            "workflow_class": "coding_change",
        },
    )

    assert profile["status"] == "allowed"
    assert profile["profile_id"] == "workflow:coding_change_tdd"
    assert profile["decision_source"] == "workflow_run"
    assert profile["policy"]["policy_id"] == "phase-1"
    assert profile["policy"]["workflow_id"] == "coding_change_tdd"


def test_empty_prompt_profile_needs_clarification():
    profile = _build_profile(prompt="")

    assert profile["status"] == "needs_clarification"
    assert profile["profile_id"] == "needs_clarification:input"
    assert profile["decision_source"] == "input"


def test_every_routing_source_has_an_explicit_decision_and_an_unknown_one_needs_configuration():
    assert _build_profile()["decision_source"] == "direct_chat_safe"
    signature = _build_profile(prompt="Traceback: TimeoutError in checkout", routing_intent="support_request",
                               routing_reason="intent:support_request_signature", routing_intent_source="signature")
    assert (signature["status"], signature["decision_source"]) == ("allowed", "support_request_signature")
    worker = _build_profile(prompt="Summarize", routing_intent="diagnosis", routing_reason="worker_profile:summary",
                            routing_intent_source="worker_profile")
    assert (worker["status"], worker["decision_source"]) == ("allowed", "worker_profile")
    unknown = _build_profile(prompt="Create a concise Word report about ticketing API integration risks.",
                             routing_intent="documentation", routing_reason="intent:documentation_keywords",
                             routing_intent_source="keywords")
    assert (unknown["status"], unknown["decision_source"]) == ("needs_configuration", "routing_source_unknown")






