"""Registers ``jira_release_status`` and ``episode_summary`` on the Knowledge MCP server. No
schema has a ``project_id``: the Workspace is the connection's."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..db import async_session_factory
from ..tools.definitions.jira_release import get_jira_release_definitions
from .mcp_governed_knowledge import run_governed_mcp_tool
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_knowledge_episode import run_episode_summary

_WORKSPACE_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."
_RELEASE_STATUS_DESCRIPTION = get_jira_release_definitions()["jira_release_status"]["function"]["description"]


def _present(arguments: dict[str, Any]) -> dict[str, Any]:
    # Unset optional arguments stay absent, so the tool applies its own defaults and bounds.
    return {key: value for key, value in arguments.items() if value is not None}


def register_knowledge_ledger_tools(server: FastMCP, authenticate: AuthenticatedContext) -> None:
    @server.tool(description=_RELEASE_STATUS_DESCRIPTION + _WORKSPACE_NOTE)
    async def jira_release_status(product: str, version: str, ctx: Context | None = None) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        arguments = {"product": product, "version": version}
        async with async_session_factory() as db:
            result = await run_governed_mcp_tool(
                db, caller=caller, tool_name="jira_release_status", arguments=arguments
            )
            await db.commit()
            return result

    @server.tool(
        description=(
            "Return what this session learned to the Workspace Knowledge: a concise summary of decisions, "
            "findings and outcomes, written as a session episode source that becomes searchable and is cited "
            "with a link to the session. Send it once near the end of the session; resending the same summary "
            "is a no-op and a changed summary replaces the session's previous one. Secrets are redacted. "
            "Needs the knowledge:write scope and a Workspace that accepts session episodes." + _WORKSPACE_NOTE
        )
    )
    async def episode_summary(
        summary: str,
        client_session_id: str,
        title: str | None = None,
        products: list[str] | None = None,
        version: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        arguments = _present(
            {
                "summary": summary,
                "client_session_id": client_session_id,
                "title": title,
                "products": products,
                "version": version,
            }
        )
        async with async_session_factory() as db:
            result = await run_episode_summary(db, caller=caller, arguments=arguments)
            await db.commit()
            return result


__all__ = ["register_knowledge_ledger_tools"]
