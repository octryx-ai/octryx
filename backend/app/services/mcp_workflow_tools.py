"""The workflows of a Workspace for an external agent over MCP.

Claude Code has no modes. Its capability comes from the workflow run it follows and from a governed
approval only:

- ``workflow_catalog``: the Workspace's published phased workflows, each with its class; each runs as
  a workflow run for a Work item.
- ``workflow_select``: follows a Work item's run or starts one once the user confirmed it
  (``mcp_workflow_run_tools``). A key that names no published workflow is an explicit state:
  ``needs_clarification`` with the available keys, or ``denied: workflow_archived``.
- ``workflow_confirm(approval_id)``: approves the pending confirmation **only** with a ticket from the
  gateway's PreToolUse ``ask`` (``agent_gateway/confirmation``), i.e. after the user accepted Claude
  Code's own permission prompt. Without a ticket it answers ``needs_confirmation`` with the
  platform link.

One confirmation covers one workflow for one connection: the launcher session key or, without
one, the OAuth grant. A rejected confirmation stays rejected for that connection.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, Session, User
from .agent_gateway.confirmation import CONFIRMATION_ACTION_PREFIX, CONFIRMATION_PURPOSE, redeem_confirmation_ticket
from .approval.access import require_approval_visible
from .knowledge.episodes.policy import public_origin, session_link
from .knowledge.sources.repository_snapshot.session_target import bound_gateway_session
from .mcp_extra_tools import EXTRA_MCP_EVIDENCE_TOOLS
from .mcp_governed_knowledge import McpCaller
from .mcp_workflow_confirmation import _confirmation_scope
from .run_admission.denials import WORKFLOW_ARCHIVED
from .session.approval_decision import decide_session_approval
from .workflow_routing.explicit_selection import (
    list_published_workflow_definitions,
    resolve_explicit_workflow_selection,
)

# The evidence tools an MCP client can call (same names as the chat tools).
MCP_EVIDENCE_TOOLS = frozenset(
    {
        "knowledge_search",
        "knowledge_read",
        "knowledge_changes",
        "knowledge_code_impact",
        "jira_release_status",
        "memory_recall",
        *EXTRA_MCP_EVIDENCE_TOOLS,
    }
)
_MAX_KEY_CHARS = 120


async def mcp_workflow_catalog(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    del caller, user, arguments
    entries = [
        # workflow_select with a Work item starts or attaches a run.
        {"workflow_key": str(definition.get("key") or ""), "title": str(definition.get("title") or ""),
         "when_to_use": str(definition.get("when_to_use") or ""),
         "capability_class": definition.get("capability_class"), "needs_confirmation": True,
         "phased": True, "requires_work_item": True}
        for definition in await list_published_workflow_definitions(db, project_id=workspace_id)
    ]
    return {"state": "ok", "workspace_id": workspace_id, "workflows": entries, "count": len(entries)}


async def mcp_workflow_select(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    from .mcp_workflow_run_tools import mcp_workflow_run_select

    # A run (run_id, a Work item, or a phased workflow) binds the launcher session to the workflow run.
    run_answer = await mcp_workflow_run_select(db, caller=caller, user=user, workspace_id=workspace_id,
                                               arguments=arguments)
    if run_answer is not None:
        return run_answer
    key = str(arguments.get("workflow_key") or "").strip()[:_MAX_KEY_CHARS]
    resolution = await resolve_explicit_workflow_selection(db, workflow_key=key, project_id=workspace_id)
    archived = resolution.get("status") == WORKFLOW_ARCHIVED  # typed denial
    return {
        "state": "denied" if archived else "needs_clarification",
        "reason": str(resolution.get("status") or "unknown_key") if key else "workflow_key_required",
        "available_workflows": list(resolution.get("available_workflow_keys") or []),
    }


async def mcp_workflow_confirm(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    approval_id = str(arguments.get("approval_id") or "").strip()[:36]
    try:
        approval = await require_approval_visible(db, approval=await db.get(Approval, approval_id), user_id=user.id)
    except HTTPException:
        return {"state": "not_found", "reason": "approval_not_found"}
    action = str(approval.action or "")
    session = await db.get(Session, approval.session_id) if approval.session_id else None
    metadata = session.metadata_ if session is not None and isinstance(session.metadata_, dict) else {}
    if (
        not action.startswith(CONFIRMATION_ACTION_PREFIX)
        or approval.requested_by != user.id
        or session is None
        or session.project_id != workspace_id
        or metadata.get("purpose") != CONFIRMATION_PURPOSE
        or metadata.get("confirmation_scope") != _confirmation_scope(caller)
    ):
        # Not a confirmation of this connection: indistinguishable from an unknown id.
        return {"state": "not_found", "reason": "approval_not_found"}
    workflow_key = action.removeprefix(CONFIRMATION_ACTION_PREFIX)
    if approval.status == "pending":
        if caller.transport != "mcp":
            # Only Claude Code's MCP call, after the user accepted its permission prompt, confirms.
            return {"state": "denied", "reason": "mcp_channel_required", "approval_id": approval.id}
        gateway_session = await bound_gateway_session(
            db, user_id=user.id, workspace_id=workspace_id, session_key=caller.session_key
        )
        ticket = gateway_session is not None and await redeem_confirmation_ticket(
            db,
            session=gateway_session,
            approval_id=approval.id,
            ticket=arguments.get("confirmation_ticket"),
            tool_use_id=caller.tool_use_id,
        )
        if not ticket:
            origin = public_origin()
            return {
                "state": "needs_confirmation",
                "reason": "confirm_in_platform",
                "approval_id": approval.id,
                "confirm": {"in_platform": session_link(origin, session.id) if origin else None},
            }
        await decide_session_approval(
            db,
            approval_id=approval.id,
            decider_id=user.id,
            decision="approved",
            reason="Confirmed by the user in the Claude Code permission prompt.",
        )
    # A confirmed run start continues with the Work item it was filed for.
    item = str(metadata.get("work_item_id") or "")
    return await mcp_workflow_select(
        db, caller=caller, user=user, workspace_id=workspace_id,
        arguments={"workflow_key": workflow_key, **({"work_item": item} if item else {})},
    )


__all__ = [
    "MCP_EVIDENCE_TOOLS",
    "mcp_workflow_catalog",
    "mcp_workflow_confirm",
    "mcp_workflow_select",
]
