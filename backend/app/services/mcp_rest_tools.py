"""Custom REST operations for devices: two Knowledge MCP tools, ``rest_operations`` and ``rest_call``.

The Knowledge MCP registers its tools statically at startup, but REST operations are database rows that differ per
Workspace and role (``rest_connector``). So a device gets exactly two tools:

- ``rest_operations(query?)``: the operations the caller may use in the connection's Workspace, with their model
  description, read/write class and the parameter schema *for this caller* (scoped parameters left out, exactly as
  the chat offers them, ``rest_connector.tool_surface``);
- ``rest_call(operation, arguments)``: runs one of them through the chat's governed dispatch
  (``tools.registry.execute_tool_with_plugins``): the work-role filter, the Workspace tool policy, the run class of
  the operation, the central approval gate, then the executor's grants, data scope and audit. Nothing of that is
  re-implemented here, so a device can never get further than the chat.

Both pass the Knowledge MCP's own chain first (``mcp_governed_knowledge.run_mcp_tool_chain``: OAuth scope, active
user, rate limit, connection Workspace, audit). The Workspace must be one the person may read; an operation the
caller is not offered there (another Workspace's grant, no grant, disabled) is answered as unknown, never as
"not granted", so it stays invisible.

A write needs the ``knowledge:write`` scope and a person's approval for every call (``tool_approval_gate`` rule
``device_external_write``): the device gets ``approval_required`` with the approval id, a person decides in Octryx,
and the device repeats the same call. The connection's credentials never leave the server; the device sees results.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session_factory
from ..models import User
from ..tools.context import ToolContext
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.result_content import mcp_result_checked
from .mcp_extra_scope import chat_tool_project_config, refusal
from .mcp_governed_knowledge import READ_SCOPE, WRITE_SCOPE, McpCaller, failure, run_mcp_tool_chain
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .run_capability.worker_profiles import worker_tool_context_state

REST_WORKER = "mcp_rest_call"
UNKNOWN_OPERATION = refusal("not_found", "rest_operation_unknown",
                            "No REST operation of that name is available to you in this Workspace; "
                            "call rest_operations for the list.")
_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."


async def _context(db: AsyncSession, caller: McpCaller, user: User, workspace: str, session_id: str) -> ToolContext:
    """The context a chat turn of this person in this Workspace would have, with the device worker's run class."""
    from .work_role_model.surfaces import mcp_grant

    config = await chat_tool_project_config(db, user_id=str(user.id), workspace_id=workspace)
    context = ToolContext(
        user_id=str(user.id),
        project_ids=[workspace],
        roles=list(config.get("user_roles") or []),  # the chat's platform roles (``viewer`` when none)
        session_id=session_id,
        project_config=config,
        db=db,
        request_id=caller.request_ref,
        run_capability=worker_tool_context_state(REST_WORKER),
    )
    context.work_role_grant = await mcp_grant(db, str(user.id), workspace)
    return context


async def _offered(context: ToolContext) -> list[dict[str, Any]]:
    """The caller's ``rest__`` tools as the chat would offer them (grants, Workspace tool policy, work roles)."""
    from ..tools.visibility import filter_tool_definitions_by_visibility
    from .rest_connector.tool_surface import list_rest_tool_definitions
    from .tool_access_policy import filter_tool_definitions_for_project_policy
    from .work_role_model.surfaces import filter_definitions

    definitions = await list_rest_tool_definitions(context.db, context)
    definitions = filter_tool_definitions_by_visibility(definitions, context.project_config)
    definitions = filter_definitions(definitions, context.work_role_grant)
    return filter_tool_definitions_for_project_policy(definitions, context.project_config)


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
    """One ``rest_operations`` / ``rest_call`` for an MCP caller; the caller commits."""

    async def execute(user: User, workspace: str, session_id: str) -> dict[str, Any]:
        context = await _context(db, caller, user, workspace, session_id)
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
