"""Governed discovery of MCP resources and prompts: answered from the Workspace catalog, without a connection."""

from __future__ import annotations

from dataclasses import dataclass

from ...tools.context import ToolContext
from ..tool_approval.rules import tool_approval_requirement
from .resource_audit import DISPATCH_DISCOVERY, OUTCOME_DENIED, record_mcp_resource_discovery
from .resource_decision import McpResourceDecision, blocked_mcp_resource_result
from .resource_gate import (
    McpResourceRef,
    annotate_lost_governance_audit,
    audit_mcp_resource_decision,
    execution_scope_tags,
    mcp_resource_approval_subject,
    resolve_mcp_resource_index,
    unverifiable_decision_for,
)
from .resource_index import MirroredMcpResourceEntry
from .resource_policy import decide_mcp_resource
from .resource_states import DISCOVERY_STATE_ENFORCED, DISCOVERY_STATE_NONE_VISIBLE, DISCOVERY_STATE_NOT_MIRRORED


@dataclass(frozen=True, slots=True)
class McpResourceListing:
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
