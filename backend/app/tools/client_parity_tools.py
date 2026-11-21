"""The Octryx client's workflow-run, approval, task and Knowledge tools in the chat.

The chat must be able to work like the client. The client reaches
these through its MCP server (``mcp_parity_dispatch.PARITY_MCP_TOOLS``, ``mcp_platform_tools``); the chat runs the same
handlers with an MCP caller built from the chat (``chat_mcp_caller``):

- the user and Workspace are the chat session's (never a tool argument); a chat without exactly one Workspace gets the
  client's ``needs_configuration`` answer;
- transport ``chat`` and the chat's own session in the launcher session's place, so ``workflow_run_status`` and
  ``workflow_action_request`` act on the run this chat follows, and ``workflow_select`` continues a run here;
- the scopes are the client's full grant: what the person may do is decided by the handlers' own rules (run access,
  requester, approval visibility), the Workspace policy and, for every write, the person's per-call confirmation
  (``tool_approval_gate`` rule ``chat_platform_write``), which replaces Claude Code's permission prompt.

Reads stay free.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import ToolContext

# Every scope the client's grant can carry for these tools; the chat's limits come from the rules above.
_CHAT_SCOPES = ("workflow:read", "workflow:execute", "sessions:read", "knowledge:read", "knowledge:write",
                "tasks:read", "read")
CHAT_CLIENT_NAME = "octryx-chat"


def _chat_workspaces(context: ToolContext) -> tuple[str, ...]:
    """The chat's own Workspace when the turn has one, else the person's Workspaces.

    Example prompts: "What's the status of my current workflow run?", "Summarise my latest
    workflow run". ``context.project_ids`` holds every Workspace of the person, so a member of two Workspaces got
    "No Workspace is set for this MCP connection" from ``workflow_run_status`` and ``product_run_list`` in a chat that
    sits in exactly one Workspace; Haiku answered with OAuth configuration steps instead of "no run". The chat
    session's Workspace (``project_config["project_id"]``) is the binding, as a launcher grant's would be.
    """
    own = str((context.project_config or {}).get("project_id") or "").strip()
    if own:
        return (own,)
    return tuple(dict.fromkeys(str(item).strip() for item in context.project_ids or () if str(item).strip()))


def chat_mcp_caller(context: ToolContext) -> Any:
    """The MCP caller of a chat turn: its user, its Workspace binding and its own session."""
    from ..services.mcp_governed_knowledge import CHAT_TRANSPORT, McpCaller

    projects = _chat_workspaces(context)
    return McpCaller(user_id=str(context.user_id), grant_id=None, scopes=_CHAT_SCOPES, bound_project_ids=projects,
                     client_name=CHAT_CLIENT_NAME, transport=CHAT_TRANSPORT,
                     chat_session_id=str(context.session_id or "") or None)


def _error(exc: HTTPException) -> dict[str, Any]:
    return {"error": str(exc.detail), "status_code": exc.status_code}


class _ClientParityTool:
    """One ``mcp_parity_dispatch`` tool as a chat tool (scope, Workspace, handler, content check, audit)."""

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.mcp_parity_dispatch import run_parity_mcp_tool

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        arguments = {key: value for key, value in dict(params).items() if value is not None}
        try:
            return await run_parity_mcp_tool(context.db, caller=chat_mcp_caller(context), tool_name=self.name,
                                             arguments=arguments)
        except HTTPException as exc:
            return _error(exc)


class _ClientPlatformTool:
    """One ``mcp_platform_tools`` read as a chat tool, bound to the chat's Workspaces like a grant binding."""

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..models import User
        from ..services.mcp_platform_tools import MCP_PLATFORM_TOOL_HANDLERS

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        user = await context.db.get(User, context.user_id)
        if user is None or not user.is_active:
            return {"error": "Unknown user", "status_code": 403}
        bound = [str(item) for item in context.project_ids or () if str(item).strip()] or None
        try:
            return await MCP_PLATFORM_TOOL_HANDLERS[self.name](context.db, user=user, bound_project_ids=bound,
                                                               arguments=dict(params))
        except HTTPException as exc:
            return _error(exc)


class _ClientKnowledgeTool:
    """A client Knowledge read keyed by user (and the chat's Workspaces as the grant binding): projects and graph."""

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..models import User
        from ..services.mcp_entity_graph_tools import MCP_ENTITY_GRAPH_TOOL_HANDLERS
        from ..services.mcp_knowledge import mcp_list_projects

        if context.db is None:
            return {"error": "Database session is required", "status_code": 500}
        user = await context.db.get(User, context.user_id)
        if user is None or not user.is_active:
            return {"error": "Unknown user", "status_code": 403}
        try:
            if self.name == "knowledge_projects":
                bound = [str(item) for item in context.project_ids or () if str(item).strip()] or None
                return await mcp_list_projects(context.db, user=user, bound_project_ids=bound)
            return await MCP_ENTITY_GRAPH_TOOL_HANDLERS[self.name](context.db, user=user, arguments=dict(params))
        except HTTPException as exc:
            return _error(exc)


def _tool(base: type, name: str, description: str) -> type:
    return type(f"Client_{name}", (base,), {"name": name, "description": description})


CLIENT_RUN_READ_TOOLS = (
    _tool(_ClientParityTool, "workflow_catalog", "The Workspace's governed workflows."),
    _tool(_ClientParityTool, "workflow_run_status", "The workflow run this chat follows, or a given run."),
    _tool(_ClientParityTool, "approval_get", "One approval you may see."),
    _tool(_ClientParityTool, "product_run_list", "The newest workflow runs and task runs you may read."),
    _tool(_ClientPlatformTool, "approval_list", "Approvals you may see, by status."),
    _tool(_ClientPlatformTool, "task_list", "Your scheduled tasks."),
    _tool(_ClientPlatformTool, "task_runs", "A task's recent runs."),
    _tool(_ClientPlatformTool, "policy_effective", "A Workspace's effective command policy."),
)
CLIENT_RUN_WRITE_TOOLS = (
    _tool(_ClientParityTool, "workflow_select", "Continue an active workflow run in this chat."),
    _tool(_ClientParityTool, "workflow_decide", "Decide what the run this chat follows waits for."),
    _tool(_ClientParityTool, "workflow_action_request", "A platform action for the run this chat follows."),
)
# Gap B group 4: the client's Knowledge extras. The chat's own counterparts cover the rest: office files through its
# office tools (the client sends file bytes because the files are on its machine), episode summaries through the
# automatic turn capture and ``knowledge_episode_summary``.
CLIENT_KNOWLEDGE_READ_TOOLS = (
    _tool(_ClientParityTool, "knowledge_sources", "The Workspace's Knowledge sources."),
    _tool(_ClientKnowledgeTool, "knowledge_projects", "The Workspaces you may target."),
    _tool(_ClientKnowledgeTool, "entity_search", "Search knowledge-graph entities."),
    _tool(_ClientKnowledgeTool, "entity_neighbors", "An entity's graph neighborhood."),
)
CLIENT_KNOWLEDGE_WRITE_TOOLS = (
    _tool(_ClientParityTool, "knowledge_feedback", "Rate an Octryx answer like the chat's thumbs."),
)
CLIENT_RUN_TOOLS = (*CLIENT_RUN_READ_TOOLS, *CLIENT_RUN_WRITE_TOOLS, *CLIENT_KNOWLEDGE_READ_TOOLS,
                    *CLIENT_KNOWLEDGE_WRITE_TOOLS)

__all__ = [
    "CLIENT_KNOWLEDGE_READ_TOOLS",
    "CLIENT_KNOWLEDGE_WRITE_TOOLS",
    "CLIENT_RUN_READ_TOOLS",
    "CLIENT_RUN_TOOLS",
    "CLIENT_RUN_WRITE_TOOLS",
    "chat_mcp_caller",
]
