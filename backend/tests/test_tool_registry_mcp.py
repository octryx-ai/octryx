"""MCP bridge and admin tool definitions and MCP bridge tool execution through the manager."""

import pytest

from app.plugins.mcp.models import MCPTool
from app.tools.context import ToolContext
from app.tools.registry import execute_tool, get_tool_definitions


def test_mcp_bridge_tool_definitions_present():
    definitions = get_tool_definitions("diagnosis")
    names = {item["function"]["name"] for item in definitions}

    assert "list_mcp_servers" in names
    assert "list_mcp_server_tools" in names
    assert "call_mcp_server_tool" in names
    assert "run_test_suite" in names
    assert "run_sast_suite" in names
    assert "lint_and_format_workspace" in names
    assert "analyze_codebase_patterns" in names
    assert "build_pull_request_description" in names
    assert "git_file_intelligence" in names
    assert "git_coupling_map" in names
    assert "git_function_blame" in names
    assert "git_conflict_predictor" in names
    assert "git_pr_context" in names
    assert "git_knowledge_extract" in names
    assert "self_review_workspace_diff" in names


def test_admin_tool_definitions_include_change_and_admin_tools():
    definitions = get_tool_definitions("admin")
    names = {item["function"]["name"] for item in definitions}

    assert "write_workspace_file" in names
    assert "create_office_document" in names
    assert "admin_create_user" in names


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_mcp_bridge_tools_execute_via_manager(db, monkeypatch):
    from tests.mcp_capability_support import RecordingMcpManager, create_mcp_workspace, enable_capability, mirror_tools

    discovered_tools = [
        MCPTool(
            name="resolve-library-id",
            description="Resolve Context7 library identifiers",
            input_schema={
                "type": "object",
                "properties": {
                    "libraryName": {"type": "string", "description": "Library name"},
                    "limit": {"type": "integer", "description": "Maximum results"},
                },
                "required": ["libraryName"],
            },
            server_name="context7",
            server_id="context7",
        )
    ]

    class FakeManager(RecordingMcpManager):
        def get_tools(self, name=None):
            assert name in (None, "context7")
            return discovered_tools

        async def call_tool(self, name, tool_name, arguments):
            assert name == "context7"
            assert tool_name == "resolve-library-id"
            assert arguments == {"libraryName": "react"}
            return {"success": True, "content": [{"type": "text", "text": "react -> /facebook/react"}]}

    manager = FakeManager()
    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", manager)

    # The bridge lists and connects servers only from the persisted,
    # Workspace-scoped registry. MCP servers are also deny-by-default per
    # project; the bridge only works for servers the project explicitly
    # enables via mcp_policy. Capability governance additionally needs a
    # verifiable workspace and an enabled binding for the tool.
    workspace = await create_mcp_workspace(db)
    await mirror_tools(db, workspace, manager.get_tools("context7"), server_name="context7")
    await enable_capability(db, workspace, "resolve-library-id", risk="read", server_name="context7")
    project = workspace.project
    ctx = ToolContext(
        user_id="u1",
        project_ids=[project.id],
        roles=["admin"],
        session_id="s1",
        project_config={"project_id": project.id, "mcp_policy": {"enabled_servers": ["context7"]}},
        db=db,
        workspace_root="/tmp",
    )

    servers_result = await execute_tool("list_mcp_servers", {}, ctx)
    tools_result = await execute_tool("list_mcp_server_tools", {"server_name": "context7"}, ctx)
    call_result = await execute_tool(
        "call_mcp_server_tool",
        {"server_name": "context7", "tool_name": "resolve-library-id", "arguments": {"libraryName": "react"}},
        ctx,
    )

    assert servers_result["count"] == 1
    assert servers_result["servers"][0]["name"] == "context7"
    assert tools_result["count"] == 1
    assert tools_result["tools"][0]["name"] == "resolve-library-id"
    assert tools_result["tools"][0]["arguments"][0]["name"] == "libraryName"
    assert call_result["success"] is True
    assert call_result["content"][0]["text"] == "react -> /facebook/react"
    # The call connected through the registry, not a process-global server entry.
    assert manager.connects == ["context7"]
