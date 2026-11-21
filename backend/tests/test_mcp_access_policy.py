"""Contract tests for project-level MCP server access gating."""

import pytest

from app.plugins.mcp.models import MCPServerConfig
from app.services.mcp_access_policy import (
    blocked_mcp_server_result,
    mcp_server_access_decision,
)
from app.tools.context import ToolContext
from app.tools.mcp_bridge import CallMcpServerToolTool, ListMcpServersTool
from app.tools.registry import execute_tool_with_plugins


def _context(project_config: dict | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["member"],
        session_id="session-1",
        project_config=project_config or {},
    )


def test_server_denied_without_policy() -> None:
    decision = mcp_server_access_decision("github", {})
    assert decision.allowed is False
    assert decision.reason == "mcp_server_not_active_for_project"


def test_enabled_server_is_allowed() -> None:
    decision = mcp_server_access_decision("github", {"mcp_policy": {"enabled_servers": ["GitHub"]}})
    assert decision.allowed is True
    assert decision.reason == "explicit_server_activation"


def test_disabled_wins_over_enabled() -> None:
    decision = mcp_server_access_decision(
        "github",
        {"mcp_policy": {"enabled_servers": ["github"], "disabled_servers": ["github"]}},
    )
    assert decision.allowed is False
    assert decision.reason == "explicit_server_deactivation"


def test_allow_all_requires_explicit_true() -> None:
    assert mcp_server_access_decision("github", {"mcp_policy": {"allow_all": True}}).allowed is True
    assert mcp_server_access_decision("github", {"mcp_policy": {"allow_all": "yes"}}).allowed is False


def test_missing_server_name_is_denied() -> None:
    decision = mcp_server_access_decision("", {"mcp_policy": {"allow_all": True}})
    assert decision.allowed is False
    assert decision.reason == "missing_server_name"


def test_blocked_result_names_policy_key() -> None:
    result = blocked_mcp_server_result(mcp_server_access_decision("jira", {}))
    assert result["blocked_by"] == "mcp_access_policy"
    assert "mcp_policy" in result["error"]
    assert result["mcp_server"] == "jira"


@pytest.mark.asyncio
async def test_bridge_call_tool_blocked_without_policy() -> None:
    result = await CallMcpServerToolTool().execute(
        {"server_name": "github", "tool_name": "create_issue"},
        _context(),
    )
    assert result["blocked_by"] == "mcp_access_policy"
    assert result["reason"] == "mcp_server_not_active_for_project"


@pytest.mark.asyncio
async def test_bridge_list_servers_hides_blocked_servers(monkeypatch) -> None:
    class FakeManager:
        def list_servers(self):
            return [MCPServerConfig(name="github", command="npx", description="GitHub MCP")]

        async def is_connected(self, _name):
            return True

        def get_tools(self, _name=None):
            return [object()]

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())

    result = await ListMcpServersTool().execute({}, _context())
    assert result["count"] == 0
    assert result["servers"] == []


@pytest.mark.asyncio
async def test_direct_mcp_fqn_execution_denies_without_project_activation(monkeypatch) -> None:
    class FakeManager:
        async def call_tool(self, _server_name, _tool_name, _params):
            return {"success": True, "should_not_execute": True}

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())

    result = await execute_tool_with_plugins("mcp__github__create_issue", {}, _context())

    assert result["blocked_by"] == "mcp_access_policy"
    assert result["reason"] == "mcp_server_not_active_for_project"
    assert result["tool_execution"]["category"] == "denied_by_policy"
    assert "should_not_execute" not in result
