"""Workspace-registry boundary for direct fully-qualified MCP dispatch."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import ToolContext


async def dispatch_registered_mcp_tool(
    *,
    context: ToolContext,
    mcp_client_manager: Any,
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from app.web._helpers.context_runtime import _MCP_CATALOG

    from ..services.mcp_server_registry_connections import connect_mcp_server
    from ..services.mcp_workspace_context import resolve_workspace_context

    workspace = resolve_workspace_context(context)
    if context.db is None or not workspace.resolved:
        return {
            "error": f"MCP server '{server_name}' has no governed Workspace registry context",
            "mcp_server": server_name,
            "mcp_tool": tool_name,
            "source": "mcp",
            "error_category": "inactive_server",
            "reason": workspace.reason or "missing_database_context",
        }
    try:
        await connect_mcp_server(
            context.db,
            name=server_name,
            workspace_id=workspace.workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=context.user_id,
            mcp_client_manager=mcp_client_manager,
        )
    except HTTPException as exc:
        return {
            "error": str(exc.detail),
            "mcp_server": server_name,
            "mcp_tool": tool_name,
            "source": "mcp",
            "error_category": "inactive_server",
            "reason": "mcp_registry_connection_denied",
        }
    return await mcp_client_manager.call_tool(server_name, tool_name, arguments)


__all__ = ["dispatch_registered_mcp_tool"]
