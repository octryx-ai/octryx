"""Deterministic matrix for execution profile and policy-sensitive context combinations."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.models import CodeRepository
from app.services.execution_profile_service import build_execution_profile
from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
)
from app.services.project_resource_policy import repository_operation_policy, require_repository_operation
from app.services.tool_access_policy import tool_project_policy_decision
from app.tools.visibility import tool_visibility_decision


def _profile(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "prompt": "Check the current status.",
        "requested_agent_type": "chat",
        "effective_agent_type": "chat",
        "execution_strategy": "direct",
        "execution_strategy_reason": "strategy:direct_default",
        "routing_intent": "diagnosis",
        "routing_reason": "intent:diagnosis_default",
        "routing_intent_confidence": 0.42,
        "routing_intent_source": "default",
        "workflow_id": "",
        "workflow_contract": {},
    }
    params.update(overrides)
    return build_execution_profile(**params).to_metadata()




@pytest.mark.parametrize(
    ("label", "overrides", "expected"),
    [
        (
            "chat",
            {},
            {"status": "allowed", "profile_id": "direct_chat_safe", "decision_source": "direct_chat_safe"},
        ),
        (
            "admin",
            {
                "requested_agent_type": "admin",
                "effective_agent_type": "admin",
                "agent_type_explicit": True,
            },
            {
                "status": "allowed",
                "profile_id": "direct_chat_safe",
                "decision_source": "explicit_ui_context",
            },
        ),
        (
            "workflow",
            {
                "prompt": "What do we know about the release process?",
                "execution_strategy": "workflow",
                "execution_strategy_reason": "workflow_run:phase",
                "routing_intent": "knowledge",
                "routing_reason": "workflow_run:phase",
                "routing_intent_confidence": 1.0,
                "routing_intent_source": "policy",
                "workflow_id": "knowledge_request",
                "workflow_contract": {"workflow_id": "knowledge_request"},
                "workflow_routing_policy_resolution": {
                    "source": "db",
                    "status": "matched",
                    "selection_source": "workflow_run",
                    "workflow_id": "knowledge_request",
                    "workflow_class": "knowledge_request",
                },
            },
            {"status": "allowed", "profile_id": "workflow:knowledge_request", "decision_source": "workflow_run"},
        ),
        (
            "task",
            {
                "prompt": "Synchronize the linked task evidence.",
                "requested_agent_type": "task",
                "effective_agent_type": "task",
                "execution_strategy": "workflow",
                "execution_strategy_reason": "task_workflow:matched",
                "routing_intent": "task",
                "routing_reason": "task_workflow:matched",
                "routing_intent_confidence": 1.0,
                "routing_intent_source": "policy",
                "workflow_id": "task_sync",
                "workflow_contract": {"workflow_id": "task_sync"},
            },
            {"status": "allowed", "profile_id": "workflow:task_sync", "decision_source": "policy"},
        ),
    ],
)
def test_execution_profile_context_matrix_records_explicit_decisions(
    label: str,
    overrides: dict[str, Any],
    expected: dict[str, str],
) -> None:
    profile = _profile(**overrides)

    assert label
    assert profile["status"] == expected["status"]
    assert profile["profile_id"] == expected["profile_id"]
    assert profile["decision_source"] == expected["decision_source"]


def test_profile_takes_no_router_input_and_records_no_router_call() -> None:
    # No pre-turn model call feeds the profile, so provider failures surface
    # only as runtime attempts of the governed turn, never as a routing state.
    with pytest.raises(TypeError):
        _profile(llm_decision=object())

    profile = _profile()

    assert profile["status"] == EXECUTION_PROFILE_STATUS_ALLOWED
    assert profile["decision_source"] == "direct_chat_safe"
    assert profile["llm_router"] == {"status": "not_used"}


@pytest.mark.parametrize(
    ("label", "project_config", "expected_visible", "expected_reason"),
    [
        ("connector_inactive", {}, False, "connector_not_active_for_project"),
        ("connector_active_by_legacy_config", {"jira_url": "https://jira.example.test"}, True, "project_connector_config_present"),
        ("connector_active_by_explicit_state", {"connectors": {"jira": {"enabled": True}}}, True, "explicit_connector_activation"),
    ],
)
def test_connector_activation_matrix_controls_model_visible_tools(
    label: str,
    project_config: dict[str, Any],
    expected_visible: bool,
    expected_reason: str,
) -> None:
    decision = tool_visibility_decision("search_jira_tickets", project_config)

    assert label
    assert decision.visible is expected_visible
    assert decision.connector == "jira"
    assert decision.reason == expected_reason




def test_task_tool_policy_decision_is_deny_by_default_for_denied_task_tool() -> None:
    decision = tool_project_policy_decision(
        "knowledge_search",
        {"tool_policy": {"denylist": ["knowledge_search"]}},
    )

    assert decision.allowed is False
    assert decision.policy == "project_tool_policy"
    assert decision.reason == "denylist"
    assert decision.matched_rule == "denylist"


@pytest.mark.parametrize(
    ("label", "operation_policy", "allowed_operations", "blocked_operations"),
    [
        (
            "unconfigured_repository_defaults_to_read_only",
            {},
            ("read", "index"),
            ("branch", "write", "pr", "migration"),
        ),
        (
            "explicit_readonly_repository",
            {"read": True, "index": True, "branch": False, "write": False, "pr": False, "migration": False},
            ("read", "index"),
            ("branch", "write", "pr", "migration"),
        ),
        (
            "explicit_write_repository",
            {"read": True, "index": True, "branch": True, "write": True, "pr": True, "migration": False},
            ("read", "index", "branch", "write", "pr"),
            ("migration",),
        ),
    ],
)
def test_repository_operation_matrix_requires_explicit_write_policy(
    label: str,
    operation_policy: dict[str, bool],
    allowed_operations: tuple[str, ...],
    blocked_operations: tuple[str, ...],
) -> None:
    repo = CodeRepository(
        project_id="project-1",
        name="service-api",
        provider="bitbucket",
        repo_root="/workspace/service-api",
        remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
        config_json={"operation_policy": operation_policy} if operation_policy else {},
    )
    policy = repository_operation_policy(repo)

    assert label
    for operation in allowed_operations:
        assert policy[operation] is True
        require_repository_operation(repo, operation)
    for operation in blocked_operations:
        assert policy[operation] is False
        with pytest.raises(HTTPException) as exc_info:
            require_repository_operation(repo, operation)
        assert exc_info.value.status_code == 403
        assert operation in str(exc_info.value.detail)
