"""Governed Knowledge evidence and Memory tools for external CLIs on the Knowledge MCP. They run the same governed chain
as the chat's tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, User
from ..tools.context import ToolContext
from ..tools.knowledge_evidence.changes import KnowledgeChangesTool
from ..tools.knowledge_evidence.read import KnowledgeReadTool
from ..tools.knowledge_evidence.search import KnowledgeSearchTool
from ..tools.knowledge_memory.recall import MemoryRecallTool
from ..tools.knowledge_memory.remember import MemoryRememberTool
from ..tools.result_content import mcp_result_checked
from .mcp_auto_session import record_mcp_tool_activity
from .mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit
from .mcp_knowledge_release_status import McpJiraReleaseStatusTool
from .run_admission.denials import WORKSPACE_REQUIRED
from .run_capability.direct_dispatch import execute_with_capability_check
from .run_capability.worker_profiles import worker_tool_context_state
from .tool_access_policy import tool_project_policy_decision

WORKSPACE_HEADER = "x-octryx-workspace"
SESSION_HEADER = "x-octryx-session"
READ_SCOPE = "knowledge:read"
WRITE_SCOPE = "knowledge:write"
_MAX_WORKSPACE_REF_CHARS = 64

GOVERNED_MCP_TOOLS: dict[str, tuple[Any, str]] = {
    # The platform's one Knowledge search: the same class, schema and name as in the chat.
    "knowledge_search": (KnowledgeSearchTool(), READ_SCOPE),
    "knowledge_read": (KnowledgeReadTool(), READ_SCOPE),
    "knowledge_changes": (KnowledgeChangesTool(), READ_SCOPE),
    # Live, read-only Jira query (GET only) with the chat's Jira gate (``mcp_knowledge_release_status``).
    "jira_release_status": (McpJiraReleaseStatusTool(), READ_SCOPE),
    "memory_recall": (MemoryRecallTool(), READ_SCOPE),
    "memory_remember": (MemoryRememberTool(), WRITE_SCOPE),
}
# Connector reads, diagrams and governed web search/fetch: the chat's classes behind the chat's gates.
GOVERNED_MCP_TOOLS.update(EXTRA_GOVERNED_MCP_TOOLS)
MEMORY_MCP_TOOLS = frozenset({"memory_recall", "memory_remember"})


def _code_impact_tool(caller: McpCaller) -> Any:
    from .mcp_code_impact import McpKnowledgeCodeImpactTool

    return McpKnowledgeCodeImpactTool(session_key=caller.session_key)

FAILURES: dict[str, dict[str, str]] = {
    "needs_configuration": {
        "state": "needs_configuration",
        "reason": WORKSPACE_REQUIRED,  # the one typed reason of every missing-Workspace refusal
        "error": (
            "No Workspace is set for this MCP connection. Bind the OAuth grant to one Workspace or set the "
            "X-Octryx-Workspace header in the MCP client configuration."
        ),
    },
    "not_found": {"state": "not_found", "error": "No Knowledge workspace is in scope for this session."},
    "scope_required": {"state": "denied", "error": "The OAuth grant lacks the scope this tool needs."},
    "tool_policy_denied": {
        "state": "denied",
        "reason": "tool_denied_by_project_policy",
        "error": "The Workspace tool policy does not allow this tool.",
    },
    "user_inactive": {"state": "denied", "error": "The MCP OAuth user is not active."},
}


@dataclass(frozen=True, slots=True)
class McpCaller:
    # From the verified OAuth token and the connection, never from tool arguments.

    user_id: str
    grant_id: str | None
    scopes: tuple[str, ...]
    bound_project_ids: tuple[str, ...] = ()
    workspace_header: str | None = None
    client_name: str = "mcp-client"
    request_ref: str | None = None
    # "mcp" for the native protocol, "http" for the REST tool endpoint; recorded in the audit row.
    transport: str = "mcp"
    # The launcher session key (``X-Octryx-Session``) of an octryx-claude connection: a
    # transport setting, never a tool argument. It names the session's recorded repository binding.
    session_key: str | None = None
    # Claude Code's tool_use id of this MCP call (``_meta["claudecode/toolUseId"]``), native MCP only.
    tool_use_id: str | None = None
    # A platform chat running the client's handler (chat and client parity): transport ``chat`` and the
    # chat's own session, which follows runs like a launcher session does. Only the chat tools build such a caller;
    # the person confirmed the call in the chat (``tool_approval.gate``) before any write handler runs.
    chat_session_id: str | None = None


CHAT_TRANSPORT = "chat"


# Tools that need the connection's transport settings (the session key) are built per call.
CALLER_BOUND_MCP_TOOLS: dict[str, tuple[Callable[[McpCaller], Any], str]] = {
    "knowledge_code_impact": (_code_impact_tool, READ_SCOPE),
}


def failure(reason: str) -> dict[str, str]:
    return dict(FAILURES[reason])


def resolve_mcp_workspace(caller: McpCaller) -> str | dict[str, str]:
    bound = tuple(dict.fromkeys(item for item in caller.bound_project_ids if item))
    requested = str(caller.workspace_header or "").strip()
    if requested:
        if len(requested) > _MAX_WORKSPACE_REF_CHARS or (bound and requested not in bound):
            # Outside the grant is indistinguishable from unknown.
            return failure("not_found")
        return requested
    if len(bound) == 1:
        return bound[0]
    return failure("needs_configuration")


async def _project_policy_allows(db: AsyncSession, workspace_id: str, tool_name: str) -> bool:
    config = (await db.execute(select(Project.config).where(Project.id == workspace_id))).scalar_one_or_none()
    return tool_project_policy_decision(tool_name, config if isinstance(config, dict) else {}).allowed


def _recorded_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # Memory arguments are named, never copied.
    if tool_name in MEMORY_MCP_TOOLS:
        return {"argument_names": sorted(str(key) for key in arguments)}
    return arguments


McpExecute = Callable[[User, str, str], Awaitable[dict[str, Any]]]


async def run_governed_mcp_tool(
    db: AsyncSession, *, caller: McpCaller, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if tool_name in CALLER_BOUND_MCP_TOOLS:
        factory, required_scope = CALLER_BOUND_MCP_TOOLS[tool_name]
        tool = factory(caller)
    else:
        tool, required_scope = GOVERNED_MCP_TOOLS[tool_name]

    async def execute(user: User, workspace: str, session_id: str) -> dict[str, Any]:
        if not await _project_policy_allows(db, workspace, tool_name):
            # The chat's project tool policy, on the Workspace row (the MCP call has no turn config).
            return failure("tool_policy_denied")
        context = ToolContext(
            user_id=str(user.id),
            project_ids=[workspace],
            roles=[],
            session_id=session_id,
            project_config={"project_id": workspace},
            db=db,
            request_id=caller.request_ref,
            run_capability=worker_tool_context_state("mcp_governed_knowledge"),
        )
        result = await execute_with_capability_check(tool, dict(arguments), context)
        from .devices.device_turn_results import keep_turn_diagram

        await keep_turn_diagram(db, caller=caller, user=user, workspace=workspace, tool_name=tool_name, result=result)
        return await mcp_result_checked(tool_name, result, workspace)  # content check

    return await run_mcp_tool_chain(db, caller=caller, tool_name=tool_name, arguments=arguments,
                                    required_scope=required_scope, execute=execute)


async def run_mcp_tool_chain(
    db: AsyncSession, *, caller: McpCaller, tool_name: str, arguments: dict[str, Any], required_scope: str,
    execute: McpExecute, workspace_optional: bool = False,
) -> dict[str, Any]:
    # Shared, so a tool with its own dispatch keeps exactly the same chain.
    if required_scope not in caller.scopes:
        return failure("scope_required")
    user = await db.get(User, caller.user_id)
    if user is None or not user.is_active:
        return failure("user_inactive")
    await enforce_mcp_knowledge_rate_limit(api_key_id=caller.grant_id, user_id=caller.user_id, tool_name=tool_name)
    workspace = resolve_mcp_workspace(caller)
    session_id = await record_mcp_tool_activity(
        db,
        user=user,
        grant_id=caller.grant_id,
        client_name=caller.client_name,
        tool_name=tool_name,
        arguments=_recorded_arguments(tool_name, arguments),
    )
    if isinstance(workspace, dict) and workspace_optional:
        workspace = ""  # a person-scoped tool runs on the person's own data without a connection Workspace
    result: dict[str, Any] = workspace if isinstance(workspace, dict) else await execute(user, workspace, session_id)
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=str(user.id),
        api_key_id=caller.grant_id,
        api_key_project_id=",".join(caller.bound_project_ids) or None,
        tool_name=tool_name,
        arguments={"project_id": workspace if isinstance(workspace, str) else ""},
        result=result,
        # A refusal is a fixed state; only that token is audited, never a message or memory text.
        status_value=str(result.get("state") or "error") if "error" in result else "success",
        transport=caller.transport,
    )
    return result


__all__ = [
    "CALLER_BOUND_MCP_TOOLS",
    "CHAT_TRANSPORT",
    "GOVERNED_MCP_TOOLS",
    "MEMORY_MCP_TOOLS",
    "SESSION_HEADER",
    "WORKSPACE_HEADER",
    "McpCaller",
    "resolve_mcp_workspace",
    "run_governed_mcp_tool",
    "run_mcp_tool_chain",
]
