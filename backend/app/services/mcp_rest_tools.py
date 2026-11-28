"""Custom REST operations for devices: two Knowledge MCP tools, ``rest_operations`` and ``rest_call``. Operations are
per-Workspace rows, so a device gets two static tools instead of one per operation."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session_factory
from ..models import User
from ..tools.context import ToolContext
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.result_content import mcp_result_checked
from .mcp_extra_scope import refusal
from .mcp_governed_knowledge import READ_SCOPE, WRITE_SCOPE, McpCaller, failure, run_mcp_tool_chain
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_registry_tools import session_tool_context

REST_WORKER = "mcp_rest_call"
UNKNOWN_OPERATION = refusal("not_found", "rest_operation_unknown",
                            "No REST operation of that name is available to you in this Workspace; "
                            "call rest_operations for the list.")
_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."


async def _offered(context: ToolContext) -> list[dict[str, Any]]:
    from .rest_connector.tool_surface import list_rest_tool_definitions
    from .tool_offer_policy import policy_visible_definitions

    return policy_visible_definitions(await list_rest_tool_definitions(context.db, context), context)


def _entry(definition: dict[str, Any]) -> dict[str, Any]:
    from ..tools.definitions import get_tool_definition_metadata

    function = definition["function"]
    writes = get_tool_definition_metadata(function["name"]).risk == "write"
    return {"operation": function["name"], "description": function.get("description") or "",
            "class": "write" if writes else "read", "parameters": function.get("parameters") or {}}


async def rest_operations(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip().lower()
    entries = [_entry(definition) for definition in await _offered(context)]
    if query:
        entries = [entry for entry in entries
                   if query in entry["operation"].lower() or query in entry["description"].lower()]
    return {"operations": entries, "count": len(entries)}


async def rest_call(context: ToolContext, arguments: dict[str, Any], scopes: tuple[str, ...]) -> dict[str, Any]:
    from ..tools.registry import execute_tool_with_plugins

    name = str(arguments.get("operation") or "").strip()
    offered = {entry["operation"]: entry for entry in map(_entry, await _offered(context))}
    if name not in offered:
        return dict(UNKNOWN_OPERATION)
    if offered[name]["class"] == "write" and WRITE_SCOPE not in scopes:
        return failure("scope_required")
    call_arguments = arguments.get("arguments")
    if call_arguments is not None and not isinstance(call_arguments, dict):
        return refusal("denied", "invalid_arguments", "arguments must be an object of the operation's parameters.")
    return await execute_tool_with_plugins(name, dict(call_arguments or {}), context)


async def run_rest_mcp_tool(db: AsyncSession, *, caller: McpCaller, tool_name: str,
                            arguments: dict[str, Any]) -> dict[str, Any]:
    async def execute(user: User, workspace: str, session_id: str) -> dict[str, Any]:
        context = await session_tool_context(db, caller, user, workspace, session_id, worker=REST_WORKER)
        authorized = await authorized_workspace({}, context)
        if type(authorized) is dict:
            return authorized
        if tool_name == "rest_operations":
            return await rest_operations(context, arguments)
        result = await rest_call(context, arguments, caller.scopes)
        return await mcp_result_checked(str(arguments.get("operation") or tool_name), result, workspace)

    return await run_mcp_tool_chain(db, caller=caller, tool_name=tool_name, arguments=arguments,
                                    required_scope=READ_SCOPE, execute=execute)


def register_rest_tools(server: FastMCP, authenticate: AuthenticatedContext) -> None:
    async def call(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        async with async_session_factory() as db:
            result = await run_rest_mcp_tool(db, caller=caller, tool_name=tool_name, arguments=arguments)
            await db.commit()
            return result

    @server.tool(
        description=(
            "List the custom REST API operations you may use in this Workspace: name, description, class (read or "
            "write) and the parameters to pass to rest_call. query narrows by name or description." + _NOTE
        )
    )
    async def rest_operations(query: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "rest_operations", {"query": query})

    @server.tool(
        description=(
            "Call one custom REST API operation from rest_operations with its arguments. Octryx applies your access "
            "and data scope and holds the credentials. A write returns approval_required with an approval_id: a "
            "person approves it in Octryx, then repeat exactly the same call (needs the knowledge:write scope)."
            + _NOTE
        )
    )
    async def rest_call(operation: str, arguments: dict[str, Any] | None = None,
                        ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "rest_call", {"operation": operation, "arguments": arguments})


__all__ = ["REST_WORKER", "register_rest_tools", "rest_call", "rest_operations", "run_rest_mcp_tool"]
