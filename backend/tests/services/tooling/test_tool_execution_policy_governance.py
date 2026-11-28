import pytest

from app.services.tool_access_policy import (
    blocked_tool_result,
    tool_is_allowed_by_project_policy,
    tool_project_policy_decision,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins


def test_unknown_tool_requires_governance_metadata_before_execution() -> None:
    decision = tool_project_policy_decision("mystery_enterprise_tool", {})

    assert decision.allowed is False
    assert decision.policy == "tool_governance_metadata"
    assert decision.reason == "unknown_tool_requires_metadata"
    assert decision.requires_explicit_allow is True


def test_high_risk_connector_tool_requires_explicit_allow_rule() -> None:
    decision = tool_project_policy_decision(
        "create_jira_ticket",
        {"connectors": {"jira": {"enabled": True}}},
    )

    assert decision.allowed is False
    assert decision.policy == "project_tool_policy_explicit_allow"
    assert decision.reason == "high_risk_tool_requires_explicit_allow"
    assert decision.owner_type == "connector"
    assert decision.risk == "write"


def test_explicit_allow_rule_enables_high_risk_connector_tool() -> None:
    decision = tool_project_policy_decision(
        "create_jira_ticket",
        {
            "connectors": {"jira": {"enabled": True}},
            "tool_policy": {"allowlist": ["create_jira_ticket"]},
        },
    )

    assert decision.allowed is True
    assert decision.policy == "project_tool_policy"
    assert decision.matched_rule == "allowlist"
    assert tool_is_allowed_by_project_policy(
        "create_jira_ticket",
        {
            "connectors": {"jira": {"enabled": True}},
            "tool_policy": {"allowlist": ["create_jira_ticket"]},
        },
    )


def test_active_read_connector_tool_does_not_need_explicit_allow_rule() -> None:
    decision = tool_project_policy_decision(
        "search_jira_tickets",
        {"connectors": {"jira": {"enabled": True}}},
    )

    assert decision.allowed is True
    assert decision.policy == "default_platform_policy"
    assert decision.risk == "read"


def test_read_only_project_policy_still_blocks_write_tools() -> None:
    decision = tool_project_policy_decision(
        "write_workspace_file",
        {"project_role": "support"},
    )

    assert decision.allowed is False
    assert decision.policy == "project_read_only_tools"
    assert decision.reason == "change_tool_in_read_only_project"
    assert blocked_tool_result("write_workspace_file", decision)["error"] == (
        "Blocked by the project read-only tool policy."
    )


@pytest.mark.asyncio
async def test_unknown_tool_execution_is_denied_before_registry_dispatch() -> None:
    result = await execute_tool_with_plugins(
        "mystery_enterprise_tool",
        {},
        ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["member"],
            session_id="session-1",
            project_config={},
            db=None,
            workspace_root="/tmp/workspace",
        ),
    )

    assert result["policy"] == "tool_governance_metadata"
    assert result["policy_decision"]["reason"] == "unknown_tool_requires_metadata"


@pytest.mark.asyncio
async def test_a_published_workflows_platform_action_is_its_own_explicit_allow() -> None:
    def _context(**extra) -> ToolContext:
        return ToolContext(user_id="user-1", project_ids=[], roles=["member"], session_id="session-1",
                           project_config={"connectors": {"jira": {"enabled": True}}}, db=None,
                           workspace_root="/tmp/workspace", **extra)

    chat = await execute_tool_with_plugins("add_jira_comment", {"ticket_id": "ZT-1", "body": "q"}, _context())
    assert chat.get("policy_decision", {}).get("reason") == "high_risk_tool_requires_explicit_allow"

    action = await execute_tool_with_plugins("add_jira_comment", {"ticket_id": "ZT-1", "body": "q"},
                                             _context(workflow_platform_action=True))
    assert action.get("policy_decision", {}).get("reason") != "high_risk_tool_requires_explicit_allow"

    denied = ToolContext(user_id="user-1", project_ids=[], roles=["member"], session_id="session-1",
                         project_config={"connectors": {"jira": {"enabled": True}},
                                         "tool_policy": {"denylist": ["add_jira_comment"]}},
                         db=None, workspace_root="/tmp/workspace", workflow_platform_action=True)
    refused = await execute_tool_with_plugins("add_jira_comment", {"ticket_id": "ZT-1", "body": "q"}, denied)
    assert refused.get("policy_decision", {}).get("allowed") is False
