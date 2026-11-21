"""Governed ``web_search`` and ``web_fetch`` on the Knowledge MCP.

``web_search`` is the chat's ``WebSearchTool``: it calls ``services/web_search/service.
governed_search``, which owns the provider, the data-policy admission, the platform blocklist, the
trusted-source registry and the anomaly quarantine. The Workspace's search mode (``open`` or
``trusted_only``) and its provider key are read from the Workspace row by the service itself, as in
the chat; the MCP path supplies nothing else. The data classification is resolved from the Workspace
and the grant's MCP auto session.

``web_fetch`` is the chat's ``WebFetchTool`` (pinned public-web egress, redirect-bounded, no
environment proxy). The chat tool itself checks the requested URL against the same source registry
the search results pass, with one shared check (``web_search/fetch_policy.web_fetch_refusal``): a
blocked source (platform blocklist or a ``blocked`` entry) is ``denied`` / ``source_blocked``, and a
``trusted_only`` Workspace fetches only from a trusted source (``denied`` / ``source_not_trusted``).
A redirect target is checked by the egress policy, not by the registry.

Both tools first authorize the connection Workspace for the user (``not_found`` otherwise).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..tools.context import ToolContext
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.runtime_impl._runtime_bash_web import WebFetchTool
from ..tools.runtime_impl._runtime_web_search_tools import WebSearchTool
from .mcp_extra_scope import WorkspaceBoundTool


class McpWebFetchTool:
    """The chat's ``web_fetch`` behind the Workspace's source registry."""

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
