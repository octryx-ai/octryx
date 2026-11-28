"""The registry's tools on the session MCP endpoint: the chat's visible set (``tool_offer_policy``), called through the
registry's governed dispatch inside the MCP chain; a write or admin call waits for approval (worker ``mcp_session``)."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool as MCPTool
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..tools.context import ToolContext
from ..tools.definitions import get_tool_definition_metadata
from ..tools.definitions.surfaces import served_over_mcp
from .mcp_extra_scope import chat_tool_project_config, refusal, user_platform_roles
from .mcp_governed_knowledge import READ_SCOPE, WRITE_SCOPE, McpCaller, failure, run_mcp_tool_chain
from .run_capability.worker_profiles import worker_tool_context_state
from .tool_offer_policy import policy_visible_definitions

MCP_SESSION_WORKER = "mcp_session"
#: Tools on the person's own data that also run without a connection Workspace (the platform default policy applies):
#: ``knowledge_projects`` is how a client finds the Workspace to bind.
PERSON_SCOPED_TOOLS = frozenset({"knowledge_projects", "task_list", "task_runs", "approval_list", "policy_effective",
                                 "entity_search", "entity_neighbors"})
#: The agent type whose registry definitions the endpoint serves (the chat's default).
AGENT_TYPE = "diagnosis"
NOT_OFFERED = refusal("not_found", "tool_not_offered",
                      "No tool of that name is offered to you in this session; use tool_search to find one.")


async def session_tool_context(db: AsyncSession, caller: McpCaller, user: User, workspace: str, session_id: str, *,
                               worker: str = MCP_SESSION_WORKER) -> ToolContext:
    from .work_role_model.surfaces import mcp_grant

    if workspace:
        config = await chat_tool_project_config(db, user_id=str(user.id), workspace_id=workspace)
    else:
        config = {"user_roles": await user_platform_roles(db, str(user.id))}
    context = ToolContext(
        user_id=str(user.id),
        project_ids=[workspace] if workspace else [],
        roles=list(config.get("user_roles") or []),  # the chat's platform roles (``viewer`` when none)
        session_id=session_id,
        project_config=config,
        db=db,
        request_id=caller.request_ref,
        capability_type=AGENT_TYPE,
        run_capability=worker_tool_context_state(worker),
    )
    context.work_role_grant = await mcp_grant(db, str(user.id), workspace) if workspace else None
    context.mcp_caller = caller
    return context


def _name(definition: dict[str, Any]) -> str:
    return str((definition.get("function") or {}).get("name") or "")


def served_definitions(skip: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    from ..tools.registry import get_all_tools_with_plugins

    return [definition for definition in get_all_tools_with_plugins(agent_type=AGENT_TYPE)
            if served_over_mcp(_name(definition)) and _name(definition) not in skip]


def offered_definitions(context: ToolContext, skip: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    from .run_capability.chat_writes import is_chat_connector_write_tool

    # A high-risk connector write the Workspace has not explicitly allowed is offered as in a chat: there the person
    # confirms each call, here a person approves each call in Octryx.
    return policy_visible_definitions(served_definitions(skip), context,
                                      confirmed_per_call=is_chat_connector_write_tool)


def mcp_tool(definition: dict[str, Any]) -> MCPTool:
    function = definition.get("function") or {}
    return MCPTool(name=str(function.get("name") or ""), description=str(function.get("description") or ""),
                   inputSchema=dict(function.get("parameters") or {"type": "object", "properties": {}}))


def required_scope(tool_name: str) -> str:
    from .mcp_parity_dispatch import PARITY_MCP_TOOLS
    from .mcp_platform_tools import MCP_PLATFORM_TOOL_SCOPES

    # A tool with its own grant scope keeps it; every other read or write needs the Knowledge read or write scope.
    if tool_name in PARITY_MCP_TOOLS:
        return PARITY_MCP_TOOLS[tool_name][1]
    if tool_name in MCP_PLATFORM_TOOL_SCOPES:
        return MCP_PLATFORM_TOOL_SCOPES[tool_name]
    return WRITE_SCOPE if get_tool_definition_metadata(tool_name).risk in {"write", "admin"} else READ_SCOPE


async def member_workspace(db: AsyncSession, user_id: str, workspace: str) -> bool:
    from .access_control import get_project_role_for_user

    return not workspace or bool(await get_project_role_for_user(db, user_id, workspace))


async def offered_tools(db: AsyncSession, caller: McpCaller, workspace: str, skip: frozenset[str]) -> list[MCPTool]:
    # ``workspace`` empty: the connection names none, and only the person-scoped tools are offered.
    user = await db.get(User, caller.user_id)
    if user is None or not user.is_active or not await member_workspace(db, str(user.id), workspace):
        return []
    context = await session_tool_context(db, caller, user, workspace, "")
    return [mcp_tool(definition) for definition in offered_definitions(context, skip)
            if workspace or _name(definition) in PERSON_SCOPED_TOOLS]


async def call_registry_tool(db: AsyncSession, *, caller: McpCaller, tool_name: str, arguments: dict[str, Any],
                             skip: frozenset[str]) -> dict[str, Any]:
    from ..tools.registry import execute_tool_with_plugins

    async def execute(user: User, workspace: str, session_id: str) -> dict[str, Any]:
        if not await member_workspace(db, str(user.id), workspace):
            return failure("not_found")  # outside the person's Workspaces is indistinguishable from unknown
        context = await session_tool_context(db, caller, user, workspace, await _session_id(db, caller, user,
                                                                                            workspace, session_id))
        # Never trusts an earlier listing or tool_search: the visible set is decided again for every call.
        offered = {_name(definition) for definition in offered_definitions(context, skip)}
        if tool_name not in offered or not (workspace or tool_name in PERSON_SCOPED_TOOLS):
            return dict(NOT_OFFERED)
        return await execute_tool_with_plugins(tool_name, dict(arguments), context)

    scope = required_scope(tool_name)
    result = await run_mcp_tool_chain(db, caller=caller, tool_name=tool_name, arguments=_argument_names(arguments),
                                      required_scope=scope, execute=execute,
                                      workspace_optional=tool_name in PERSON_SCOPED_TOOLS)
    return {**result, "required_scope": scope} if scope not in caller.scopes else result


async def _session_id(db: AsyncSession, caller: McpCaller, user: User, workspace: str, activity: str) -> str:
    # The person's session the call belongs to, which holds its approvals across turns: the platform session of the
    # device or runner job the launcher session runs (each turn has a launcher session of its own), else that launcher
    # session, else the connection's daily activity session.
    from .devices.device_turn_results import caller_device_job
    from .mcp_workflow_run_session import _gateway

    job = await caller_device_job(db, caller, user, workspace)
    if job is not None:
        return str(job.session_id)
    gateway = await _gateway(db, caller, user, workspace) if workspace else None
    return str(gateway.id) if gateway is not None else activity


def _argument_names(arguments: dict[str, Any]) -> dict[str, Any]:
    # The activity row keeps the argument names only; the tool gets the values through ``execute``.
    return {"argument_names": sorted(str(key) for key in arguments)}


__all__ = [
    "MCP_SESSION_WORKER",
    "NOT_OFFERED",
    "PERSON_SCOPED_TOOLS",
    "call_registry_tool",
    "member_workspace",
    "mcp_tool",
    "offered_definitions",
    "offered_tools",
    "required_scope",
    "served_definitions",
    "session_tool_context",
]
