import pytest

from app.services.runtime_policy_bundle import normalize_runtime_policy_config
from app.services.tool_access_policy import filter_tool_definitions_for_project_policy, tool_project_policy_decision


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {}}}}


def _names(definitions: list[dict]) -> list[str]:
    return [definition["function"]["name"] for definition in definitions]


def test_project_tool_policy_allow_patterns_filter_visible_tools() -> None:
    definitions = [
        _tool("search_jira_users"),
        _tool("list_jira_versions"),
        _tool("knowledge_search"),
        _tool("create_jira_ticket"),
        _tool("bash"),
    ]

    filtered = filter_tool_definitions_for_project_policy(
        definitions,
        {
            "tool_policy": {
                "allow_patterns": ["search_jira_*", "list_jira_*", "knowledge_*"],
                "deny_patterns": ["*_delete", "create_*"],
            }
        },
    )

    assert _names(filtered) == ["search_jira_users", "list_jira_versions", "knowledge_search"]


def test_project_tool_policy_supports_future_read_prefix_convention() -> None:
    definitions = [
        _tool("read_workspace_file"),
        _tool("read_office_document"),
        _tool("search_jira_users"),
        _tool("write_workspace_file"),
    ]

    filtered = filter_tool_definitions_for_project_policy(
        definitions,
        {"tool_policy": {"allow_patterns": ["read_*"]}},
    )

    assert _names(filtered) == ["read_workspace_file", "read_office_document"]


def test_the_runtime_policy_carries_no_tool_policy() -> None:
    assert "tool_policy" not in normalize_runtime_policy_config({"tool_policy": {"denylist": ["bash"]}})


def test_a_tool_policy_nested_in_the_runtime_policy_is_not_enforced() -> None:
    definitions = [_tool("bash"), _tool("knowledge_search")]
    filtered = filter_tool_definitions_for_project_policy(
        definitions, {"runtime_policy": {"tool_policy": {"denylist": ["bash"]}}}
    )
    assert _names(filtered) == ["bash", "knowledge_search"]


def test_high_risk_grants_are_exact_name_only() -> None:
    from app.services.tool_access_policy_rules import _tool_policy_explicitly_allows

    policy = {
        "allow_patterns": ["*"],
        "high_risk_grants": ["commit_and_push_repository_branch"],
        "allowlist": ["add_jira_comment"],
    }
    # Dedicated grant list wins; allowlist names keep working.
    assert _tool_policy_explicitly_allows("commit_and_push_repository_branch", policy) == "high_risk_grants"
    assert _tool_policy_explicitly_allows("add_jira_comment", policy) == "allowlist"
    # A broad visibility pattern must NOT count as a high-risk grant.
    assert _tool_policy_explicitly_allows("create_bitbucket_pull_request", policy) is None


def test_high_risk_grant_counts_next_to_visibility_rules_in_the_dispatch_decision() -> None:
    # The dispatch decision reads the visibility policy; a grant must survive into it,
    # or a policy with any allow pattern could never unlock a granted high-risk tool.
    project_config = {
        "tool_policy": {
            "allow_patterns": ["create_bitbucket_*"],
            "high_risk_grants": ["commit_and_push_repository_branch"],
        }
    }

    granted = tool_project_policy_decision("commit_and_push_repository_branch", project_config)
    pattern_only = tool_project_policy_decision("create_bitbucket_pull_request", project_config)

    assert granted.allowed is True
    assert (granted.policy, granted.matched_rule) == ("project_tool_policy", "high_risk_grants")
    # A visibility pattern alone still never unlocks a high-risk tool.
    assert pattern_only.allowed is False
    assert pattern_only.reason == "high_risk_tool_requires_explicit_allow"


def test_connector_policy_disabled_tools_feed_runtime_tool_visibility_policy() -> None:
    definitions = [_tool("search_jira_tickets"), _tool("get_jira_ticket"), _tool("knowledge_search")]
    project_config = {
        "connector_policies": {
            "jira": {
                "disabled_tools": ["search_jira_tickets"],
            }
        }
    }

    filtered = filter_tool_definitions_for_project_policy(definitions, project_config)
    decision = tool_project_policy_decision("search_jira_tickets", project_config)

    assert _names(filtered) == ["get_jira_ticket", "knowledge_search"]
    assert decision.allowed is False
    assert decision.policy == "project_tool_policy"
    assert decision.reason == "denylist"


def test_a_runtime_policy_save_with_a_nested_tool_policy_is_refused() -> None:
    from fastapi import HTTPException

    from app.services.admin.project._admin_project_config_normalize import _normalize_project_config_value

    with pytest.raises(HTTPException) as refused:
        _normalize_project_config_value("runtime_policy", {"tool_policy": {"denylist": ["bash"]}})
    assert refused.value.status_code == 400
