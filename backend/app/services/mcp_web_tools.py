"""Governed ``web_search`` and ``web_fetch`` on the Knowledge MCP. The chat's tools, with the same data-policy admission
and source registry."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..tools.context import ToolContext
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.runtime_impl._runtime_bash_web import WebFetchTool
from ..tools.runtime_impl._runtime_web_search_tools import WebSearchTool
from .mcp_extra_scope import WorkspaceBoundTool


class McpWebFetchTool:
    name = "web_fetch"

    def __init__(self) -> None:
        self._tool = WebFetchTool()

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        # The chat tool applies the one shared source check itself (``web_search/fetch_policy``).
        return await self._tool.execute(params, replace(context, project_config={
            **(context.project_config or {}), "project_id": authorized.project_id,
        }))


WEB_MCP_TOOLS: dict[str, Any] = {
    "web_search": WorkspaceBoundTool(WebSearchTool()),
    "web_fetch": McpWebFetchTool(),
}

__all__ = ["WEB_MCP_TOOLS", "McpWebFetchTool"]
