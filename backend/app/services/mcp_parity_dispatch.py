"""One governed runner for the workflow and work-status MCP tools. The same chain as the governed Knowledge tools:
scope, active user, rate limit, connection Workspace, audit."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..tools.result_content import mcp_result_checked
from .knowledge.access.authorization import authorize_tool_workspace
from .knowledge.ledger.errors import EvidenceLedgerError
from .mcp_auto_session import record_mcp_tool_activity
from .mcp_extra_tools import EXTRA_HANDLER_MCP_TOOLS
from .mcp_governed_knowledge import CHAT_TRANSPORT, McpCaller, failure, resolve_mcp_workspace
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit
from .mcp_work_status_tools import mcp_approval_get, mcp_product_run_list
from .mcp_workflow_run_tools import (
    PHASE_OUTPUT_MCP_HANDLERS,
    mcp_workflow_action_request,
    mcp_workflow_decide,
    mcp_workflow_run_status,
)
from .mcp_workflow_tools import (
    mcp_workflow_catalog,
    mcp_workflow_confirm,
    mcp_workflow_select,
)

Handler = Callable[..., Awaitable[dict[str, Any]]]

PARITY_MCP_TOOLS: dict[str, tuple[Handler, str]] = {
    "workflow_catalog": (mcp_workflow_catalog, "workflow:read"),
    "workflow_select": (mcp_workflow_select, "workflow:read"),
    "workflow_confirm": (mcp_workflow_confirm, "workflow:execute"),
    # The run an octryx-claude session follows, and platform actions on the server for it.
    "workflow_run_status": (mcp_workflow_run_status, "workflow:read"),
    "workflow_action_request": (mcp_workflow_action_request, "workflow:execute"),
    # The requester's decision of what the run waits for, only after the user's permission prompt.
    "workflow_decide": (mcp_workflow_decide, "workflow:execute"),
    # A phase's structured output on the session's run (only while its phase offers the tool): A's Definition of
    # Ready, B's test contract, C's reproduction, E's incident hypothesis.
    **{tool: (handler, "workflow:execute") for tool, handler in PHASE_OUTPUT_MCP_HANDLERS.items()},
    "approval_get": (mcp_approval_get, "sessions:read"),
    "product_run_list": (mcp_product_run_list, "sessions:read"),
}
# The Knowledge sources listing and answer feedback.
PARITY_MCP_TOOLS.update(EXTRA_HANDLER_MCP_TOOLS)
# Argument values the activity row may keep: identifiers only.
_RECORDED_ARGUMENTS = frozenset({"workflow_key", "approval_id", "run_id", "action", "file_name", "work_item"})


async def run_parity_handler(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    # Inside the session MCP endpoint's chain (``mcp_registry_tools``), which already checked the user, the rate
    # limit and the Workspace and audits the call; only the tool's own scope is left.
    from .content_security.knowledge_fence import unfenced_result

    handler, required_scope = PARITY_MCP_TOOLS[tool_name]
    if required_scope not in caller.scopes:
        return failure("scope_required")
    return await handler(db, caller=caller, user=user, workspace_id=workspace_id,
                         arguments=dict(unfenced_result(arguments)))


async def run_parity_mcp_tool(
    db: AsyncSession, *, caller: McpCaller, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    # Fence markers the device's model copied are dropped: the fence is only for a model's input.
    from .content_security.knowledge_fence import unfenced_result

    arguments = unfenced_result(arguments)
    handler, required_scope = PARITY_MCP_TOOLS[tool_name]
    if required_scope not in caller.scopes:
        return failure("scope_required")
    user = await db.get(User, caller.user_id)
    if user is None or not user.is_active:
        return failure("user_inactive")
    await enforce_mcp_knowledge_rate_limit(api_key_id=caller.grant_id, user_id=caller.user_id, tool_name=tool_name)
    workspace = resolve_mcp_workspace(caller)
    if caller.transport != CHAT_TRANSPORT:  # a chat records its tool calls in its own session, not an MCP auto session
        await record_mcp_tool_activity(
            db,
            user=user,
            grant_id=caller.grant_id,
            client_name=caller.client_name,
            tool_name=tool_name,
            arguments={key: str(arguments[key])[:120] for key in _RECORDED_ARGUMENTS if key in arguments},
        )
    if isinstance(workspace, dict):
        result: dict[str, Any] = workspace
    else:
        try:
            await authorize_tool_workspace(
                db, user_id=str(user.id), project_id=workspace, allowed_project_ids=[workspace]
            )
        except EvidenceLedgerError:
            result = failure("not_found")
        else:
            result = await handler(db, caller=caller, user=user, workspace_id=workspace, arguments=dict(arguments))
            result = await mcp_result_checked(tool_name, result, workspace)  # content check
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=str(user.id),
        api_key_id=caller.grant_id,
        api_key_project_id=",".join(caller.bound_project_ids) or None,
        tool_name=tool_name,
        arguments={"project_id": workspace if isinstance(workspace, str) else ""},
        result={},
        status_value=str(result.get("state") or "ok"),
        transport=caller.transport,
    )
    return result


__all__ = ["PARITY_MCP_TOOLS", "run_parity_handler", "run_parity_mcp_tool"]
