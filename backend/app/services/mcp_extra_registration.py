"""The Knowledge MCP tools with gates of their own on MCP: connector reads and ``web_fetch``. Both runners apply the
same chain: scope, active user, rate limit, connection Workspace, audit."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..db import async_session_factory
from .mcp_connector_registration import WORKSPACE_NOTE, register_connector_tools
from .mcp_extra_tools import EXTRA_HANDLER_MCP_TOOLS
from .mcp_governed_knowledge import run_governed_mcp_tool
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_parity_dispatch import run_parity_mcp_tool


def _present(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if value is not None}


def register_extra_tools(server: FastMCP, authenticate: AuthenticatedContext) -> None:
    async def call(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        runner = run_parity_mcp_tool if tool_name in EXTRA_HANDLER_MCP_TOOLS else run_governed_mcp_tool
        async with async_session_factory() as db:
            result = await runner(db, caller=caller, tool_name=tool_name, arguments=_present(arguments))
            await db.commit()
            return result

    register_connector_tools(server, call)

    @server.tool(
        description=(
            "Fetch one public URL as markdown (default), text or html (max 2 MB). Blocked sources are refused; "
            "a trusted_only Workspace fetches only trusted sources. Read-only." + WORKSPACE_NOTE
        )
    )
    async def web_fetch(
        url: str, format: str | None = None, timeout: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "web_fetch", {"url": url, "format": format, "timeout": timeout})


__all__ = ["register_extra_tools"]
