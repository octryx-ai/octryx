"""MCP Plugin for Octryx.

This plugin is the runtime transport boundary. The database-backed registry owns
durable server configuration.
"""

import logging
from typing import Any

from app.services.error_facts import error_text

from ..core.base import BasePlugin, PluginMetadata, PluginToolDefinition
from .client import MCP_AVAILABLE, mcp_client_manager

log = logging.getLogger(__name__)

class MCPPlugin(BasePlugin):
    """Plugin for integrating MCP servers."""

    metadata = PluginMetadata(
        id="mcp",
        name="MCP (Model Context Protocol)",
        version="1.0.0",
        description="Integrates MCP servers as tools for the agent. Supports stdio, SSE, and HTTP transports.",
        author="Octryx",
        tags=["mcp", "tools", "integration", "protocol"],
        dependencies=["mcp>=1.0.0"],
    )

    def __init__(self):
        super().__init__()
        self._initialized = False

    def on_load(self) -> None:
        """Load MCP plugin and discover servers."""
        if not MCP_AVAILABLE:
            log.warning("MCP package not installed. Install with: pip install mcp")
            return

        log.info("Loading MCP plugin...")
        self._initialized = True

        log.info("MCP Plugin loaded with %s server(s)", len(mcp_client_manager.list_servers()))

    def on_unload(self) -> None:
        """Cleanup on unload."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(mcp_client_manager.shutdown())
            else:
                loop.run_until_complete(mcp_client_manager.shutdown())
        except Exception as e:
            log.error("Error during MCP shutdown: %s", error_text("mcp_shutdown_failed", e))

    def get_tools(self) -> list[PluginToolDefinition]:
        """Return MCP tool definitions for all connected servers."""
        tools = []

        if not MCP_AVAILABLE:
            return tools

        mcp_tools = mcp_client_manager.get_tools()
        for mcp_tool in mcp_tools:
            fqn_name = f"mcp_{mcp_tool.server_id}_{mcp_tool.name}"
            tools.append(
                PluginToolDefinition(
                    name=fqn_name,
                    description=f"[{mcp_tool.server_name}] {mcp_tool.description}",
                    parameters=mcp_tool.input_schema,
                )
            )

        return tools

    async def execute(self, params: dict, context: Any) -> dict:
        """Execute an MCP tool."""
        if not MCP_AVAILABLE:
            return {"error": "MCP package not installed. Install with: pip install mcp"}

        tool_name = params.get("_tool_name") or params.get("tool_name", "")

        if not tool_name.startswith("mcp_"):
            return {"error": f"Invalid MCP tool name: {tool_name}"}

        arguments = {k: v for k, v in params.items() if k not in ("_tool_name", "tool_name")}
        result = await mcp_client_manager.call_tool_by_fqn(tool_name, arguments)
        return result
