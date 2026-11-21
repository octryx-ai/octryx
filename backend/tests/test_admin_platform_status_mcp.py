"""The platform status tool names every registered MCP server, its transport and whether it is connected."""

from __future__ import annotations

from app.plugins.mcp import client as mcp_client_module
from app.plugins.mcp.client import MCPClientManager
from app.plugins.mcp.models import MCPServerConfig, TransportType
from app.tools.admin_impl._admin_platform import AdminPlatformStatusTool
from app.tools.context import ToolContext


async def test_platform_status_lists_the_mcp_servers_and_their_connection(db, monkeypatch):
    manager = MCPClientManager()
    manager.register_server(MCPServerConfig(name="tickets", command="tickets-mcp"))
    manager.register_server(MCPServerConfig(name="docs", command="", transport=TransportType.STREAMABLE_HTTP,
                                            url="https://docs.example.test/mcp"))
    manager._sessions["docs"] = object()  # a connected session
    monkeypatch.setattr(mcp_client_module, "mcp_client_manager", manager)
    context = ToolContext(user_id="admin-user", project_ids=[], roles=["operator"], session_id="status", project_config={}, db=db)

    result = await AdminPlatformStatusTool().execute({}, context)

    assert result["mcp_servers"] == [
        {"name": "tickets", "connected": False, "transport": "stdio"},
        {"name": "docs", "connected": True, "transport": "streamable-http"},
    ]


async def test_platform_status_is_refused_without_an_admin_or_operator_role(db):
    context = ToolContext(user_id="viewer", project_ids=[], roles=["viewer"], session_id="status", project_config={}, db=db)

    assert await AdminPlatformStatusTool().execute({}, context) == {
        "error": "Access denied: admin or operator role required."}
