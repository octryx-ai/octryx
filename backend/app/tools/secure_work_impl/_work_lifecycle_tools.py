"""The Octryx client's work-item lifecycle tools in the chat.

The chat must be able to work the way the client does. The client reaches these
operations through its MCP server (``services/mcp_secure_work_tools``); the chat runs exactly the same handler, inside
the chat's MCP-equivalent scope (``_chat_scope``: the person's Work scope narrowed by the session's Workspaces), so
there is one implementation and one authorization. Reads run freely; the writes are confirmed per call in a chat
(``tool_approval_gate`` rule ``chat_platform_write``).

The chat is its own agent (``agent_board.identity.chat_session_identity``): the client's claim fencing applies to its
writes exactly as to a client session's, so a chat cannot transition or re-plan an item another agent holds.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..context import ToolContext
from ._work_item_tools import _chat_scope, _error, _require_db_and_user


def client_handlers(identity: Any) -> dict[str, Any]:
    """Every client MCP handler the chat runs, as the chat's own agent ``identity`` (claims fence its writes)."""
    from ...services.agent_board.fencing import fenced_handlers
    from ...services.mcp_agent_board_tools import board_tool_handlers
    from ...services.mcp_agent_presence_tools import AGENT_PRESENCE_TOOL_HANDLERS
    from ...services.mcp_secure_work_tools import MCP_SECURE_WORK_TOOL_HANDLERS
    from ...services.mcp_work_claim_tools import work_claim_tool_handlers
    from ...services.mcp_work_handoff_tools import handoff_tool_handlers

    return {
        **fenced_handlers(MCP_SECURE_WORK_TOOL_HANDLERS, identity=identity),
        **board_tool_handlers(identity=identity),
        **work_claim_tool_handlers(identity=identity),
        **handoff_tool_handlers(identity=identity),
        **AGENT_PRESENCE_TOOL_HANDLERS,
    }


class _ClientWorkTool:
    """One client MCP handler as a chat tool, run in the chat's scope as the chat session's agent."""

    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ...services.agent_board.identity import chat_session_identity

        try:
            db, user = await _require_db_and_user(context)
            scope = await _chat_scope(db, user, context)
            identity = chat_session_identity(user_id=user.id, session_id=context.session_id,
                                             project_ids=context.project_ids)
            handler = client_handlers(identity)[self.name]
            return await handler(db, user=user, scope=scope, arguments=dict(params))
        except HTTPException as exc:
            return _error(exc)


class WorkItemFindTool(_ClientWorkTool):
    name = "work_item_find"
    description = "Find a work item by Jira source key or platform id."


class WorkItemListTool(_ClientWorkTool):
    name = "work_item_list"
    description = "List open work items to pick up."


class CodingObservabilityTool(_ClientWorkTool):
    name = "coding_observability"
    description = "Coding observability of a work item."


class WorkItemTransitionTool(_ClientWorkTool):
    name = "work_item_transition"
    description = "Transition a work item's lifecycle state."


class ChangeUnitsPlanTool(_ClientWorkTool):
    name = "change_units_plan"
    description = "Plan change units for a work item."


class ChangePlanGenerateTool(_ClientWorkTool):
    name = "change_plan_generate"
    description = "Generate a change plan from a work item's change units."


class ChangePlanDecideTool(_ClientWorkTool):
    name = "change_plan_decide"
    description = "Decide a change plan."


class WorkItemRedeclareTool(_ClientWorkTool):
    name = "work_item_redeclare"
    description = "Redeclare a work item after a declined pull request."


class CodingAgentStartTool(_ClientWorkTool):
    name = "coding_agent_start"
    description = "Start the governed coding agent for a work item's approved plan."


# ── Coordination between agents (gap B group 2): board, claims, handoffs, takeovers, presence ─────────────────
class BoardReadTool(_ClientWorkTool):
    name = "board_read"
    description = "Read the Workspace's agent message board."


class BoardPostTool(_ClientWorkTool):
    name = "board_post"
    description = "Post to the Workspace's agent message board."


class BoardAckTool(_ClientWorkTool):
    name = "board_ack"
    description = "Acknowledge board messages."


class WorkItemClaimTool(_ClientWorkTool):
    name = "work_item_claim"
    description = "Claim a work item for this chat session."


class WorkItemReleaseTool(_ClientWorkTool):
    name = "work_item_release"
    description = "Release this chat session's claim on a work item."


class WhoIsWorkingOnTool(_ClientWorkTool):
    name = "who_is_working_on"
    description = "Who is working on a work item or paths."


class AgentPresenceListTool(_ClientWorkTool):
    name = "agent_presence_list"
    description = "List the Workspace's governed coding-agent sessions."


class WorkItemHandoffReadTool(_ClientWorkTool):
    name = "work_item_handoff_read"
    description = "Read a work item's structured handoff."


class WorkItemHandoffWriteTool(_ClientWorkTool):
    name = "work_item_handoff_write"
    description = "Write the next version of a work item's handoff."


class WorkItemTakeoverRequestTool(_ClientWorkTool):
    name = "work_item_takeover_request"
    description = "Ask to take over a work item another agent holds."


class WorkItemTakeoverStatusTool(_ClientWorkTool):
    name = "work_item_takeover_status"
    description = "The status of a takeover request."


CLIENT_WORK_READ_TOOLS = (
    WorkItemFindTool,
    WorkItemListTool,
    CodingObservabilityTool,
    BoardReadTool,
    WhoIsWorkingOnTool,
    AgentPresenceListTool,
    WorkItemHandoffReadTool,
    WorkItemTakeoverStatusTool,
)
CLIENT_WORK_WRITE_TOOLS = (
    WorkItemTransitionTool,
    ChangeUnitsPlanTool,
    ChangePlanGenerateTool,
    ChangePlanDecideTool,
    WorkItemRedeclareTool,
    CodingAgentStartTool,
    BoardPostTool,
    BoardAckTool,
    WorkItemClaimTool,
    WorkItemReleaseTool,
    WorkItemHandoffWriteTool,
    WorkItemTakeoverRequestTool,
)

__all__ = [
    "CLIENT_WORK_READ_TOOLS",
    "CLIENT_WORK_WRITE_TOOLS",
    *(tool.__name__ for tool in (*CLIENT_WORK_READ_TOOLS, *CLIENT_WORK_WRITE_TOOLS)),
]
