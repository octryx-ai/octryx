"""Tests for explicit execution profile metadata."""

from __future__ import annotations

from app.services.execution_profile_service import EXECUTION_PROFILE_VERSION, build_execution_profile
from app.services.execution_profile_trace import execution_profile_trace_summary


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
    """The default reasons run as safe direct chat; the support-request signature and a worker profile are named
    sources; any other source never runs on a guess (``needs_configuration``)."""
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


def test_trace_summary_projects_decision_fields_and_drops_bulky_or_free_text_parts():
    profile = _build_profile(
        prompt="Fix the failing login test",
        routing_intent="coding",
        routing_reason="workflow_run:phase",
        routing_intent_confidence=1.0,
        routing_intent_source="policy",
        workflow_id="coding_change_tdd",
        workflow_contract={"workflow_id": "coding_change_tdd", "phases": [{"tools": ["read_workspace_file"]}]},
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
        runtime_target_id="target-1",
        runtime_label="Bedrock / nova",
    )
    # Not part of the envelope (to_metadata never emits it), so never projected.
    profile["workflow_key"] = "bug-fix-reproduction"
    profile["requirements"] = {
        "satisfied": True,
        "status": "allowed",
        "available_tools": ["read_workspace_file", "run_workspace_tests"],
        "policy_denied_tools": [],
    }
    # A router block carrying model-written free text is never copied into the summary.
    profile["llm_router"] = {"status": "invalid_response", "reasoning": "model text about the prompt"}

    summary = execution_profile_trace_summary(profile)

    assert summary == {
        "version": EXECUTION_PROFILE_VERSION,
        "status": "allowed",
        "profile_id": "workflow:coding_change_tdd",
        "decision_source": "workflow_run",
        "reason": "The workflow run's current phase governs this turn.",
        "routing_intent": "coding",
        "routing_intent_source": "policy",
        "routing_intent_confidence": 1.0,
        "execution_strategy": "direct",
        "requested_agent_type": "chat",
        "effective_agent_type": "chat",
        "workflow_id": "coding_change_tdd",
        "policy": {
            "source": "db",
            "status": "matched",
            "policy_id": "phase-1",
            "policy_version_id": "version-1",
            "matched_group_id": "group-1",
            "workflow_id": "coding_change_tdd",
            "workflow_class": "coding_change",
            "selection_state": "selected",
            "selection_reason_code": "workflow_run",
        },
        "runtime": {"runtime_target_id": "target-1", "runtime_label": "Bedrock / nova"},
        "requirements": {"status": "allowed", "satisfied": True},
    }


def test_trace_summary_bounds_text_and_drops_non_scalar_values():
    profile = _build_profile()
    profile["reason"] = "r" * 1000
    profile["decision_source"] = {"nested": "not a scalar"}

    summary = execution_profile_trace_summary(profile)

    assert summary["reason"] == "r" * 300
    assert "decision_source" not in summary
    profile["routing_intent_confidence"] = float("nan")
    assert "routing_intent_confidence" not in execution_profile_trace_summary(profile)
    assert "llm_router" not in summary
    assert "routing_reason" not in summary
    assert "workflow_contract" not in summary


def test_trace_summary_is_none_without_a_recorded_profile():
    assert execution_profile_trace_summary(None) is None
    assert execution_profile_trace_summary({}) is None
    assert execution_profile_trace_summary({"status": "  "}) is None
    assert execution_profile_trace_summary("allowed") is None
