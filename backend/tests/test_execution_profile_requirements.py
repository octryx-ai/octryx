"""Contract tests for workflow tool requirement checks feeding the execution profile."""

from app.services.execution_profile_requirements import (
    REQUIREMENT_DECISION_SOURCE,
    apply_requirement_decision_to_profile,
    evaluate_workflow_tool_requirements,
    preferred_workflow_tools,
)
from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)


def _contract(*tools: str, workflow_id: str = "jira_evidence") -> dict:
    return {
        "workflow_id": workflow_id,
        "phases": [{"id": "collect", "preferred_tools": list(tools)}],
    }


def test_preferred_tools_deduplicate_across_phases() -> None:
    contract = {
        "workflow_id": "w",
        "phases": [
            {"id": "a", "preferred_tools": ["search_jira_tickets", "knowledge_search"]},
            {"id": "b", "preferred_tools": ["knowledge_search"]},
        ],
    }
    assert preferred_workflow_tools(contract) == ("search_jira_tickets", "knowledge_search")


def test_contract_without_planned_tools_is_satisfied() -> None:
    decision = evaluate_workflow_tool_requirements(workflow_contract={}, project_config={})
    assert decision.satisfied is True
    assert decision.status == EXECUTION_PROFILE_STATUS_ALLOWED


def test_inactive_connector_yields_needs_configuration() -> None:
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets"),
        project_config={},
    )
    assert decision.satisfied is False
    assert decision.status == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert decision.inactive_connectors == ("jira",)
    assert "jira" in decision.reason


def test_configured_connector_satisfies_requirement() -> None:
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets"),
        project_config={"jira_url": "https://jira.example.com"},
    )
    assert decision.satisfied is True
    assert decision.available_tools == ("search_jira_tickets",)


def test_one_available_tool_keeps_workflow_executable() -> None:
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets", "knowledge_search"),
        project_config={},
    )
    assert decision.satisfied is True
    assert decision.available_tools == ("knowledge_search",)


def test_policy_denied_tools_yield_denied() -> None:
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("knowledge_search"),
        project_config={"tool_policy": {"denylist": ["knowledge_search"]}},
    )
    assert decision.satisfied is False
    assert decision.status == EXECUTION_PROFILE_STATUS_DENIED
    assert decision.policy_denied_tools == ("knowledge_search",)
    assert "knowledge_search" in decision.reason


def test_inactive_connector_wins_over_policy_denial_for_status() -> None:
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets", "knowledge_search"),
        project_config={"tool_policy": {"denylist": ["knowledge_search"]}},
    )
    assert decision.satisfied is False
    assert decision.status == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert decision.inactive_connectors == ("jira",)
    assert decision.policy_denied_tools == ("knowledge_search",)


def test_apply_downgrades_allowed_profile() -> None:
    profile = {"status": EXECUTION_PROFILE_STATUS_ALLOWED, "decision_source": "llm_router", "reason": "ok"}
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets"),
        project_config={},
    )
    updated = apply_requirement_decision_to_profile(profile, decision)
    assert updated["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert updated["decision_source"] == REQUIREMENT_DECISION_SOURCE
    assert updated["requirements"]["previous_status"] == EXECUTION_PROFILE_STATUS_ALLOWED
    assert updated["requirements"]["previous_decision_source"] == "llm_router"
    # The input profile is not mutated.
    assert profile["status"] == EXECUTION_PROFILE_STATUS_ALLOWED


def test_apply_preserves_already_blocked_profile() -> None:
    profile = {
        "status": EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
        "decision_source": "input",
        "reason": "Prompt is empty.",
    }
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("search_jira_tickets"),
        project_config={},
    )
    updated = apply_requirement_decision_to_profile(profile, decision)
    assert updated["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION
    assert updated["decision_source"] == "input"
    assert updated["requirements"]["satisfied"] is False


def test_apply_records_satisfied_requirements_without_status_change() -> None:
    profile = {"status": EXECUTION_PROFILE_STATUS_ALLOWED, "decision_source": "policy", "reason": "ok"}
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_contract("knowledge_search"),
        project_config={},
    )
    updated = apply_requirement_decision_to_profile(profile, decision)
    assert updated["status"] == EXECUTION_PROFILE_STATUS_ALLOWED
    assert updated["requirements"]["satisfied"] is True
