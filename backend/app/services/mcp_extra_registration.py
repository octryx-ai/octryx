"""The extra Knowledge MCP tools (Claude Code parity): connector reads, diagrams, web, sources, feedback.

Two runners, both with the same chain (scope, active user, rate limit, connection Workspace, audit):

- ``EXTRA_GOVERNED_MCP_TOOLS`` are chat tool classes for ``run_governed_mcp_tool`` (it also applies
  the project tool policy and the run-capability check);
- ``EXTRA_HANDLER_MCP_TOOLS`` are platform handlers for ``run_parity_mcp_tool``.

The tables live in ``mcp_extra_tools`` (no runner imports, so the runners can merge them); this
module registers the tools on FastMCP.

No schema has a mode, an ``agent_type``, a ``project_id``, a ``workspace_id`` or a ``user_id``: the
OAuth grant names the user and the connection names the Workspace. Unset optional arguments stay
absent, so every tool applies its own defaults and bounds.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..db import async_session_factory
from .mcp_connector_registration import WORKSPACE_NOTE, register_connector_tools
from .mcp_extra_tools import EXTRA_HANDLER_MCP_TOOLS
from .mcp_governed_knowledge import run_governed_mcp_tool
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_parity_dispatch import run_parity_mcp_tool
from .mcp_structured_graph_tools import register_structured_graph_tools


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
    register_structured_graph_tools(server, call)

    @server.tool(
        description=(
            "List the Workspace's Knowledge sources (title, source key, current revision, source_url and "
            "cite_as where known), newest first; page with limit (1-200) and offset. Read-only." + WORKSPACE_NOTE
        )
    )
    async def knowledge_sources(
        limit: int | None = None, offset: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "knowledge_sources", {"limit": limit, "offset": offset})

    @server.tool(
        description=(
            "Rate an Octryx answer (session_id, message_id of an assistant message in this Workspace): "
            "rating good|bad, optional liked/disliked texts (800 chars) and aspects {correctness|sources|"
            "completeness|clarity|tool_use|speed: liked|disliked}. Re-rating replaces it. Never put credentials "
            "in the texts (refused). Needs the knowledge:write scope." + WORKSPACE_NOTE
        )
    )
    async def knowledge_feedback(
        session_id: str,
        message_id: str,
        rating: str,
        liked: str | None = None,
        disliked: str | None = None,
        aspects: dict[str, str] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "knowledge_feedback",
            {
                "session_id": session_id,
                "message_id": message_id,
                "rating": rating,
                "liked": liked,
                "disliked": disliked,
                "aspects": aspects,
            },
        )

    @server.tool(
        description=(
            "Create a draw.io diagram from ONLY <mxCell> elements (no <mxGraphModel>, <root>, <mxfile> or root "
            "cells id 0/1; they are added). Close every <mxCell> with </mxCell>. Draw only nodes and edges your "
            "evidence supports. Returns diagram_xml (format drawio); nothing is stored." + WORKSPACE_NOTE
        )
    )
    async def create_diagram(xml: str, title: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "create_diagram", {"xml": xml, "title": title})

    @server.tool(
        description=(
            "Replace a diagram with an updated one: pass the COMPLETE new set of <mxCell> elements (same format "
            "as create_diagram) and a short change_description. Returns diagram_xml; nothing is stored."
            + WORKSPACE_NOTE
        )
    )
    async def edit_diagram(
        xml: str, title: str, change_description: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "edit_diagram", {"xml": xml, "title": title, "change_description": change_description})

    @server.tool(
        description=(
            "Continue a truncated create_diagram: pass ONLY the continuation <mxCell> elements and the partial "
            "xml as base_xml. Returns diagram_xml when complete; nothing is stored." + WORKSPACE_NOTE
        )
    )
    async def append_diagram(
        xml: str, base_xml: str | None = None, title: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "append_diagram", {"xml": xml, "base_xml": base_xml, "title": title})

    @server.tool(
        description=(
            "Search the web through the platform's governed search: the platform blocklist and the Workspace's "
            "trusted-source registry apply, and a trusted_only Workspace searches only its trusted sources. "
            "Returns titles, URLs and snippets. Read-only." + WORKSPACE_NOTE
        )
    )
    async def web_search(
        query: str,
        num_results: int | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        exclude_preprints: bool | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "web_search",
            {
                "query": query,
                "num_results": num_results,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
                "exclude_terms": exclude_terms,
                "exclude_preprints": exclude_preprints,
            },
        )

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
