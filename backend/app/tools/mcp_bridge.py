"""Lazy MCP discovery and execution bridge tools.

Every server-scoped bridge operation is gated by the project MCP access policy
(``services/mcp_access_policy.py``): a globally registered MCP server is only
listable and callable when the current project enables it.

Tool discovery and tool execution are additionally gated per capability by
``services/mcp_capability_gate.py``, so the model only ever sees the capabilities
it is allowed to dispatch, and a denied capability never reaches the remote
server even when this tool is executed outside the registry dispatch path.

MCP *resources* and *prompts* are a separate governed surface and live in
``tools/mcp_resource_bridge.py`` with their own catalog
(``services/mcp_resource_gate.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..services.mcp_access_policy import (
    McpServerAccessDecision,
    blocked_mcp_server_result,
    blocked_mcp_tool_result,
    mcp_access_for_context,
    mcp_tool_allowed,
)
from .context import ToolContext


def _server_access(params: dict, context: ToolContext) -> McpServerAccessDecision:
    return mcp_access_for_context(str(params.get("server_name") or ""), context)


async def _connect_registry_server(server_name: str, context: ToolContext) -> bool:
    """Resolve and connect a persisted server only through governed Workspace context."""
    if context.db is None:
        return False
    from app.web._helpers.context_runtime import _MCP_CATALOG

    from ..plugins.mcp.client import mcp_client_manager
    from ..services.mcp_server_registry_connections import connect_mcp_server
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if not workspace.resolved:
        return False
    try:
        await connect_mcp_server(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=context.user_id,
            mcp_client_manager=mcp_client_manager,
        )
    except HTTPException:
        return False
    return True


async def _registry_server_connected(server_name: str, context: ToolContext) -> bool:
    if context.db is None:
        return False
    from ..plugins.mcp.client import mcp_client_manager
    from ..services.mcp_server_registry_connections import mcp_server_is_connected
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if not workspace.resolved:
        return False
    try:
        return await mcp_server_is_connected(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            mcp_client_manager=mcp_client_manager,
        )
    except HTTPException:
        return False


def _compact_schema_arguments(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = {str(name).strip() for name in (schema.get("required") or []) if str(name).strip()}
    arguments: list[dict[str, Any]] = []
    for name, field in list(properties.items())[:50]:
        field = field if isinstance(field, dict) else {}
        arguments.append(
            {
                "name": name,
                "type": field.get("type", "unknown"),
                "required": name in required,
                "description": str(field.get("description") or "").strip(),
            }
        )
    return arguments


class ListMcpServersTool:
    name = "list_mcp_servers"
    description = "List registered MCP servers and their connection status."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..plugins.mcp.client import mcp_client_manager
        from ..services.mcp_server_registry_queries import list_mcp_servers
        from ..services.mcp_workspace_context import resolve_workspace_context

        include_disconnected = bool(params.get("include_disconnected", True))
        workspace = resolve_workspace_context(context)
        if context.db is None or not workspace.resolved:
            return {"error": workspace.reason or "missing_database_context", "count": 0, "servers": []}
        servers = []
        rows = await list_mcp_servers(
            context.db,
            workspace_id=workspace.workspace_id,
            mcp_client_manager=mcp_client_manager,
        )
        for row in rows:
            if not mcp_access_for_context(row["name"], context).allowed:
                continue
            connected = bool(row["connected"])
            if not include_disconnected and not connected:
                continue
            servers.append(
                {
                    "name": row["name"],
                    "description": row["description"],
                    "transport": row["transport"],
                    "url": row["url"],
                    "auto_start": bool(row["auto_start"]),
                    "connected": connected,
                    "tool_count": row["tool_count"],
                    "catalog_slug": row["catalog_slug"],
                }
            )
        return {"count": len(servers), "servers": servers}


class ListMcpServerToolsTool:
    name = "list_mcp_server_tools"
    description = (
        "Discover tools exposed by a specific MCP server without injecting every MCP schema into the model prompt."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..plugins.mcp.client import mcp_client_manager

        server_name = str(params.get("server_name") or "").strip()
        if not server_name:
            return {"error": "server_name is required"}
        access = _server_access(params, context)
        if not access.allowed:
            return blocked_mcp_server_result(access)

        auto_connect = bool(params.get("auto_connect", True))
        include_schema = bool(params.get("include_schema", False))
        search = str(params.get("search") or "").strip().lower()

        # Resolve Workspace governance before any registry resolution or
        # connection attempt. An unverifiable caller must remain zero-transport.
        from ..services.mcp_capability_listing import governed_mcp_capability_listing

        preflight = await governed_mcp_capability_listing(context, server_name=server_name, tools=[])
        if preflight.blocked_result is not None:
            return {"server_name": server_name, **preflight.blocked_result}

        connected = await _registry_server_connected(server_name, context)
        if not connected and auto_connect:
            connected = await _connect_registry_server(server_name, context)
        if not connected:
            return {"error": f"MCP server '{server_name}' is not connected"}

        tools = mcp_client_manager.get_tools(server_name)
        if search:
            tools = [
                tool for tool in tools if search in tool.name.lower() or search in (tool.description or "").lower()
            ]

        listing = await governed_mcp_capability_listing(context, server_name=server_name, tools=tools)
        if listing.blocked_result is not None:
            # Explicit denial instead of an empty-but-successful listing, which
            # would be indistinguishable from a server that exposes nothing.
            return {"server_name": server_name, **listing.blocked_result}

        payload_tools = []
        for tool, decision, approval_required in listing.visible:
            if not mcp_tool_allowed(server_name, tool.name, context.project_config):
                continue
            item = {
                "name": tool.name,
                "description": tool.description or "",
                "arguments": _compact_schema_arguments(tool.input_schema),
                "risk": decision.risk,
                "approval_required": approval_required,
            }
            if include_schema:
                item["input_schema"] = tool.input_schema or {"type": "object", "properties": {}}
            payload_tools.append(item)

        return {
            "server_name": server_name,
            "connected": True,
            "search": search,
            "count": len(payload_tools),
            "tools": payload_tools,
            # Additive: makes an empty listing unambiguous — governance ran, and
            # this is how many of the discovered capabilities it admits.
            "capability_governance": {
                "state": "enforced",
                "discovered": len(tools),
                "visible": len(payload_tools),
            },
        }


class CallMcpServerToolTool:
    name = "call_mcp_server_tool"
    description = "Call a tool on a connected MCP server by server and tool name."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..plugins.mcp.client import mcp_client_manager

        server_name = str(params.get("server_name") or "").strip()
        tool_name = str(params.get("tool_name") or "").strip()
        if not server_name:
            return {"error": "server_name is required"}
        access = _server_access(params, context)
        if not access.allowed:
            return blocked_mcp_server_result(access)
        if not tool_name:
            return {"error": "tool_name is required"}
        if not mcp_tool_allowed(server_name, tool_name, context.project_config):
            return blocked_mcp_tool_result(server_name, tool_name)

        raw_arguments = params.get("arguments")
        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        auto_connect = bool(params.get("auto_connect", True))

        from ..services.mcp_capability_gate import mcp_capability_dispatch_block

        capability_block = await mcp_capability_dispatch_block(
            server_name=server_name,
            tool_name=tool_name,
            context=context,
        )
        if capability_block is not None:
            return capability_block

        connected = await _registry_server_connected(server_name, context)
        if not connected and auto_connect:
            connected = await _connect_registry_server(server_name, context)
        if not connected:
            return {"error": f"MCP server '{server_name}' is not connected"}

        result = await mcp_client_manager.call_tool(server_name, tool_name, arguments)
        if isinstance(result, dict):
            return {
                "server_name": server_name,
                "tool_name": tool_name,
                "arguments": arguments,
                **result,
            }
        return {
            "server_name": server_name,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
        }
