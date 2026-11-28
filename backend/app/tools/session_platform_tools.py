"""The session's workflow-run, approval, task and Knowledge tools: one handler for a chat turn (its own caller,
``chat_mcp_caller``) and the session MCP endpoint (the connection's caller, ``ToolContext.mcp_caller``)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import ToolContext

# Every scope a launcher grant can carry for these tools; the chat's limits come from the rules above.
_CHAT_SCOPES = ("workflow:read", "workflow:execute", "sessions:read", "knowledge:read", "knowledge:write",
                "tasks:read", "read")
CHAT_CLIENT_NAME = "octryx-chat"


def _chat_workspaces(context: ToolContext) -> tuple[str, ...]:
    # The chat session's own Workspace is the binding, as a launcher grant's would be: a member of two Workspaces
    # otherwise got "no Workspace is set" in a chat that sits in exactly one.
    own = str((context.project_config or {}).get("project_id") or "").strip()
    if own:
        return (own,)
    return tuple(dict.fromkeys(str(item).strip() for item in context.project_ids or () if str(item).strip()))


def chat_mcp_caller(context: ToolContext) -> Any:
    from ..services.mcp_governed_knowledge import CHAT_TRANSPORT, McpCaller

    return McpCaller(user_id=str(context.user_id), grant_id=None, scopes=_CHAT_SCOPES,
                     bound_project_ids=_chat_workspaces(context), client_name=CHAT_CLIENT_NAME,
                     transport=CHAT_TRANSPORT, chat_session_id=str(context.session_id or "") or None)


def _bound(context: ToolContext) -> list[str] | None:
    caller = context.mcp_caller
    if caller is not None:
        return list(caller.bound_project_ids) or None
    return [str(item) for item in context.project_ids or () if str(item).strip()] or None


def _error(exc: HTTPException) -> dict[str, Any]:
    return {"error": str(exc.detail), "status_code": exc.status_code}


async def _active_user(context: ToolContext) -> Any:
    from ..models import User

    user = await context.db.get(User, context.user_id)
    return user if user is not None and user.is_active else None


class _SessionRunTool:

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.mcp_parity_dispatch import run_parity_handler, run_parity_mcp_tool

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        arguments = {key: value for key, value in dict(params).items() if value is not None}
        try:
            if context.mcp_caller is None:
                return await run_parity_mcp_tool(context.db, caller=chat_mcp_caller(context), tool_name=self.name,
                                                 arguments=arguments)
            user = await _active_user(context)
            if user is None:
                return {"error": "Unknown user", "status_code": 403}
            return await run_parity_handler(context.db, caller=context.mcp_caller, user=user,
                                            workspace_id=str(context.project_ids[0]), tool_name=self.name,
                                            arguments=arguments)
        except HTTPException as exc:
            return _error(exc)


class _SessionPlatformTool:

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.mcp_platform_tools import MCP_PLATFORM_TOOL_HANDLERS, require_platform_tool_scope

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        user = await _active_user(context)
        if user is None:
            return {"error": "Unknown user", "status_code": 403}
        try:
            if context.mcp_caller is not None:
                require_platform_tool_scope(self.name, context.mcp_caller.scopes)
            return await MCP_PLATFORM_TOOL_HANDLERS[self.name](context.db, user=user, bound_project_ids=_bound(context),
                                                               arguments=dict(params))
        except HTTPException as exc:
            return _error(exc)


class _SessionKnowledgeTool:

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.mcp_entity_graph_tools import MCP_ENTITY_GRAPH_TOOL_HANDLERS
        from ..services.mcp_knowledge import mcp_list_projects

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        user = await _active_user(context)
        if user is None:
            return {"error": "Unknown user", "status_code": 403}
        try:
            if self.name == "knowledge_projects":
                return await mcp_list_projects(context.db, user=user, bound_project_ids=_bound(context))
            return await MCP_ENTITY_GRAPH_TOOL_HANDLERS[self.name](context.db, user=user, arguments=dict(params))
        except HTTPException as exc:
            return _error(exc)


def _tool(base: type, name: str, description: str) -> type:
    return type(f"Session_{name}", (base,), {"name": name, "description": description})


SESSION_RUN_READ_TOOLS = (
    _tool(_SessionRunTool, "workflow_catalog", "The Workspace's governed workflows."),
    _tool(_SessionRunTool, "workflow_run_status", "The workflow run this session follows, or a given run."),
    _tool(_SessionRunTool, "approval_get", "One approval you may see."),
    _tool(_SessionRunTool, "product_run_list", "The newest workflow runs and task runs you may read."),
    _tool(_SessionPlatformTool, "approval_list", "Approvals you may see, by status."),
    _tool(_SessionPlatformTool, "task_list", "Your scheduled tasks."),
    _tool(_SessionPlatformTool, "task_runs", "A task's recent runs."),
    _tool(_SessionPlatformTool, "policy_effective", "A Workspace's effective command policy."),
)
SESSION_RUN_WRITE_TOOLS = (
    _tool(_SessionRunTool, "workflow_select", "Follow or start a workflow run in this session."),
    _tool(_SessionRunTool, "workflow_decide", "Decide what the run this session follows waits for."),
    _tool(_SessionRunTool, "workflow_action_request", "A platform action for the run this session follows."),
)
SESSION_KNOWLEDGE_READ_TOOLS = (
    _tool(_SessionRunTool, "knowledge_sources", "The Workspace's Knowledge sources."),
    _tool(_SessionKnowledgeTool, "knowledge_projects", "The Workspaces you may target."),
    _tool(_SessionKnowledgeTool, "entity_search", "Search knowledge-graph entities."),
    _tool(_SessionKnowledgeTool, "entity_neighbors", "An entity's graph neighborhood."),
)
SESSION_KNOWLEDGE_WRITE_TOOLS = (
    _tool(_SessionRunTool, "knowledge_feedback", "Rate an Octryx answer like the chat's thumbs."),
)
SESSION_PLATFORM_TOOLS = (*SESSION_RUN_READ_TOOLS, *SESSION_RUN_WRITE_TOOLS, *SESSION_KNOWLEDGE_READ_TOOLS,
                          *SESSION_KNOWLEDGE_WRITE_TOOLS)

__all__ = [
    "SESSION_KNOWLEDGE_READ_TOOLS",
    "SESSION_KNOWLEDGE_WRITE_TOOLS",
    "SESSION_PLATFORM_TOOLS",
    "SESSION_RUN_READ_TOOLS",
    "SESSION_RUN_WRITE_TOOLS",
    "chat_mcp_caller",
]
