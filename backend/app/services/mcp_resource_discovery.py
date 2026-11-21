"""Governed discovery for MCP resources and prompts.

``list_mcp_server_resources`` and ``list_mcp_server_prompts`` are answered from
the Workspace catalog and open **no connection at all**. Visibility therefore
equals dispatch permission exactly: nothing is discovered that could not also be
dispatched, a project that may see nothing never causes a handshake, and an item
added to the server after the last mirror run is invisible until an admin
re-mirrors.

An empty listing is never a bare success. The returned ``state`` says whether
this server's catalog was never mirrored for this workspace, or whether it was
mirrored and nothing in it is visible — and every discovery call, successful or
empty, leaves exactly one audit row, because "this workspace saw nothing" is a
governance fact an operator has to be able to read back.

The decision, the index, the scope rule, and the approval subject all come from
``mcp_resource_gate``, so discovery cannot drift away from dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tools.context import ToolContext
from .mcp_resource_audit import DISPATCH_DISCOVERY, OUTCOME_DENIED, record_mcp_resource_discovery
from .mcp_resource_decision import McpResourceDecision, blocked_mcp_resource_result
from .mcp_resource_gate import (
    McpResourceRef,
    annotate_lost_governance_audit,
    audit_mcp_resource_decision,
    execution_scope_tags,
    mcp_resource_approval_subject,
    resolve_mcp_resource_index,
    unverifiable_decision_for,
)
from .mcp_resource_index import MirroredMcpResourceEntry
from .mcp_resource_policy import decide_mcp_resource
from .mcp_resource_states import DISCOVERY_STATE_ENFORCED, DISCOVERY_STATE_NONE_VISIBLE, DISCOVERY_STATE_NOT_MIRRORED
from .tool_approval_rules import tool_approval_requirement


@dataclass(frozen=True, slots=True)
class McpResourceListing:
    """The governed discovery answer: visible catalog entries, or a named denial."""

    visible: tuple[tuple[MirroredMcpResourceEntry, McpResourceDecision, bool], ...] = ()
    catalog_entries: int = 0
    state: str = DISCOVERY_STATE_ENFORCED
    blocked_result: dict[str, object] | None = None
    blocked_reason: str | None = None
    # ``False`` when the one discovery row could not be written. The listing is
    # still the governed answer; the caller says the evidence is missing.
    audit_recorded: bool = True


async def governed_mcp_resource_listing(
    context: ToolContext,
    *,
    kind: str,
    server_name: str,
    tool_name: str,
) -> McpResourceListing:
    """Return the governed catalog view of one server's resources or prompts."""
    index, resolution = await resolve_mcp_resource_index(context)
    if index is None:
        decision = unverifiable_decision_for(context, resolution, kind=kind, server_name=server_name)
        recorded = await audit_mcp_resource_decision(
            context,
            decision,
            workspace_id=resolution.workspace_id,
            dispatch=DISPATCH_DISCOVERY,
            tool_name=tool_name,
            outcome=OUTCOME_DENIED,
        )
        return McpResourceListing(
            state=decision.state,
            blocked_result=annotate_lost_governance_audit(blocked_mcp_resource_result(decision), recorded),
            blocked_reason=decision.public_reason,
            audit_recorded=recorded,
        )

    scope_tags = execution_scope_tags(context)
    entries = index.entries_for(kind, server_name)
    visible: list[tuple[MirroredMcpResourceEntry, McpResourceDecision, bool]] = []
    for entry in entries:
        decision = decide_mcp_resource(
            index,
            kind=kind,
            server_name=server_name,
            identity=entry.identity,
            scope_tags=scope_tags,
        )
        if not decision.allowed:
            continue
        subject = mcp_resource_approval_subject(
            McpResourceRef(
                kind=kind,
                server_name=decision.server_name,
                identity=decision.identity,
                arguments={},
            ),
            decision,
        )
        requirement = tool_approval_requirement(subject.subject_key, context.project_config, subject=subject)
        visible.append((entry, decision, requirement.required))

    if visible:
        state = DISCOVERY_STATE_ENFORCED
    elif entries or index.has_mirror_history(kind, server_name):
        state = DISCOVERY_STATE_NONE_VISIBLE
    else:
        state = DISCOVERY_STATE_NOT_MIRRORED
    recorded = await record_mcp_resource_discovery(
        context.db,
        kind=kind,
        server_name=server_name,
        workspace_id=resolution.workspace_id,
        user_id=str(context.user_id or ""),
        session_id=str(context.session_id or ""),
        tool_name=tool_name,
        discovery_state=state,
        visible=len(visible),
        catalog_entries=len(entries),
    )
    return McpResourceListing(
        visible=tuple(sorted(visible, key=lambda item: item[0].identity)),
        catalog_entries=len(entries),
        state=state,
        audit_recorded=recorded,
    )


__all__ = ["McpResourceListing", "governed_mcp_resource_listing"]
