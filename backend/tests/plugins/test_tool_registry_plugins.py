"""Plugin tools stay out of the model-visible list and only governed plugin tools execute."""

from types import SimpleNamespace

import pytest

from app.plugins.mcp.models import MCPTool
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins


def test_get_all_tools_with_plugins_does_not_inline_mcp_tools(monkeypatch):
    class FakeManager:
        _tools = {
            "context7": [
                MCPTool(
                    name="resolve-library-id",
                    description="Resolve a library id",
                    input_schema={"type": "object", "properties": {"libraryName": {"type": "string"}}},
                    server_name="context7",
                    server_id="context7",
                )
            ]
        }

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())


def test_mcp_plugin_tools_are_not_model_visible_plugin_tools(monkeypatch):
    from app.plugins.core import manager as plugin_manager_module
    from app.tools.definitions import get_tool_definition_metadata

    class FakeMcpPlugin:
        metadata = SimpleNamespace(id="mcp")

        def get_tools(self):
            return [
                SimpleNamespace(
                    name="mcp_context7_resolve-library-id",
                    description="Direct MCP tool that must stay behind the bridge",
                    parameters={"type": "object"},
                )
            ]

        async def execute(self, _params, _context):
            return {"error": "mcp plugin should not be executed directly"}

    class FakeRegularPlugin:
        metadata = SimpleNamespace(id="regular")

        def get_tools(self):
            return [
                SimpleNamespace(
                    name="regular_plugin_tool",
                    description="Regular plugin tool",
                    parameters={"type": "object"},
                    risk="read",
                    scopes=("plugin:regular",),
                )
            ]

        async def execute(self, _params, _context):
            return {"ok": True}

    monkeypatch.setattr(
        plugin_manager_module,
        "PLUGIN_INSTANCES",
        {"mcp": FakeMcpPlugin(), "regular": FakeRegularPlugin()},
    )

    tools = plugin_manager_module.get_plugin_tools()
    names = {item["function"]["name"] for item in tools}

    assert names == {"regular_plugin_tool"}
    assert tools[0]["metadata"]["owner_type"] == "plugin"
    assert tools[0]["metadata"]["risk"] == "read"
    assert tools[0]["metadata"]["required_config"] == "plugin:regular"
    assert plugin_manager_module.get_all_tool_names() == ["regular_plugin_tool"]
    metadata = get_tool_definition_metadata("regular_plugin_tool")
    assert metadata.owner_type == "plugin"
    assert metadata.source == "plugin"
    assert metadata.risk == "read"


@pytest.mark.asyncio
async def test_execute_tool_with_plugins_does_not_execute_ungoverned_plugin_tool(monkeypatch):
    from app.plugins.core import manager as plugin_manager_module

    class FakePlugin:
        metadata = SimpleNamespace(id="unguarded")

        def get_tools(self):
            return [
                SimpleNamespace(
                    name="unguarded_plugin_tool",
                    description="Plugin tool without governance metadata",
                    parameters={"type": "object"},
                )
            ]

        async def execute(self, _params, _context):
            return {"success": True, "leaked": True}

    monkeypatch.setattr(plugin_manager_module, "PLUGIN_INSTANCES", {"unguarded": FakePlugin()})

    result = await execute_tool_with_plugins(
        "unguarded_plugin_tool",
        {"libraryName": "react"},
        ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id="s1",
            project_config={},
            db=None,
            workspace_root="/tmp",
        ),
    )

    assert result["tool_execution"]["category"] == "denied_by_policy"
    assert result["tool_execution"]["owner"]["owner_type"] == "unknown"
    assert "leaked" not in result


@pytest.mark.asyncio
async def test_execute_tool_with_plugins_allows_governed_plugin_tool(monkeypatch):
    from app.plugins.core import manager as plugin_manager_module

    class FakePlugin:
        metadata = SimpleNamespace(id="governed")

        def get_tools(self):
            return [
                SimpleNamespace(
                    name="governed_plugin_tool",
                    description="Governed plugin tool",
                    parameters={"type": "object"},
                    risk="read",
                    scopes=("plugin:governed",),
                    network_access="none",
                )
            ]

        async def execute(self, params, _context):
            return {"success": True, "echo": params.get("value")}

    monkeypatch.setattr(plugin_manager_module, "PLUGIN_INSTANCES", {"governed": FakePlugin()})

    result = await execute_tool_with_plugins(
        "governed_plugin_tool",
        {"value": "ok"},
        ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id="s1",
            project_config={},
            db=None,
            workspace_root="/tmp",
        ),
    )

    assert result == {"success": True, "echo": "ok"}
