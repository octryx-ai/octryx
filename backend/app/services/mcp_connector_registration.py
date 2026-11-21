"""Registers the read-only Confluence, Jira, ServiceNow, Kubernetes and AWS tools on the Knowledge MCP server.

The schemas mirror the chat definitions (``tools/definitions/confluence.py``, ``jira.py``,
``connectors.py``, ``knowledge_source_updates.py``); none has a ``project_id``: the Workspace is the
connection's. Every call runs through ``run_governed_mcp_tool`` (``mcp_connector_tools`` adds the
chat's connector gates). The Kubernetes and AWS reads are registered by ``mcp_infra_registration``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from .mcp_infra_registration import register_aws_tools, register_kubernetes_tools

Call = Callable[[Context | None, str, dict[str, Any]], Awaitable[dict[str, Any]]]

WORKSPACE_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."


def register_connector_tools(server: FastMCP, call: Call) -> None:
    @server.tool(
        description=(
            "Search the Workspace's Confluence pages by full text or CQL, restricted to its allowed spaces "
            "and pages. Read-only." + WORKSPACE_NOTE
        )
    )
    async def search_confluence(
        query: str | None = None,
        cql: str | None = None,
        space_key: str | None = None,
        include_child_summary: bool | None = None,
        child_limit: int | None = None,
        limit: int | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "search_confluence",
            {
                "connection": connection,
                "query": query,
                "cql": cql,
                "space_key": space_key,
                "include_child_summary": include_child_summary,
                "child_limit": child_limit,
                "limit": limit,
            },
        )

    @server.tool(description="Read an allowed Confluence page by id or title. Read-only." + WORKSPACE_NOTE)
    async def get_confluence_page(
        page_id: str | None = None,
        title: str | None = None,
        space_key: str | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "get_confluence_page",
            {"connection": connection, "page_id": page_id, "title": title, "space_key": space_key},
        )

    @server.tool(
        description=(
            "List the Confluence pages new, changed or removed in the last days (1-90), as recorded by the "
            "Workspace's Confluence Source Sync. Read-only." + WORKSPACE_NOTE
        )
    )
    async def list_confluence_page_updates(
        days: int | None = None, limit: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "list_confluence_page_updates", {"days": days, "limit": limit})

    @server.tool(
        description=(
            "Search the Workspace's Jira tickets by free text, issue key or JQL, restricted to its allowed "
            "projects. Do not invent project_key values. Read-only." + WORKSPACE_NOTE
        )
    )
    async def search_jira_tickets(
        query: str | None = None,
        jql: str | None = None,
        project_key: str | None = None,
        fix_version: str | None = None,
        fix_versions: list[str] | None = None,
        limit: int | None = None,
        start_at: int | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "search_jira_tickets",
            {
                "connection": connection,
                "query": query,
                "jql": jql,
                "project_key": project_key,
                "fix_version": fix_version,
                "fix_versions": fix_versions,
                "limit": limit,
                "start_at": start_at,
            },
        )

    @server.tool(
        description="Read one Jira ticket with its status, description and comments. Read-only." + WORKSPACE_NOTE
    )
    async def get_jira_ticket(
        ticket_id: str,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(ctx, "get_jira_ticket", {"connection": connection, "ticket_id": ticket_id})

    @server.tool(description="Read a ServiceNow record by sys_id from an allowed table. Read-only." + WORKSPACE_NOTE)
    async def get_servicenow_record(
        table: str,
        sys_id: str,
        fields: str | list[str] | None = None,
        display_value: str | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "get_servicenow_record",
            {
                "connection": connection,
                "table": table,
                "sys_id": sys_id,
                "fields": fields,
                "display_value": display_value,
            },
        )

    @server.tool(
        description="List records of an allowed ServiceNow table (sysparm_query filter). Read-only." + WORKSPACE_NOTE
    )
    async def list_servicenow_records(
        table: str,
        query: str | None = None,
        fields: str | list[str] | None = None,
        limit: int | None = None,
        display_value: str | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "list_servicenow_records",
            {
                "connection": connection,
                "table": table,
                "query": query,
                "fields": fields,
                "limit": limit,
                "display_value": display_value,
            },
        )

    @server.tool(description="List ServiceNow incidents (sysparm_query filter). Read-only." + WORKSPACE_NOTE)
    async def list_servicenow_incidents(
        query: str | None = None,
        fields: str | list[str] | None = None,
        limit: int | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "list_servicenow_incidents",
            {"connection": connection, "query": query, "fields": fields, "limit": limit},
        )

    @server.tool(description="List ServiceNow change requests (sysparm_query filter). Read-only." + WORKSPACE_NOTE)
    async def list_servicenow_changes(
        query: str | None = None,
        fields: str | list[str] | None = None,
        limit: int | None = None,
        connection: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "list_servicenow_changes",
            {"connection": connection, "query": query, "fields": fields, "limit": limit},
        )

    register_kubernetes_tools(server, call)
    register_aws_tools(server, call)


__all__ = ["WORKSPACE_NOTE", "register_connector_tools"]
