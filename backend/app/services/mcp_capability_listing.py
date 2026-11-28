"""Governed MCP capability discovery (``list_mcp_server_tools``). Discovery shows exactly what dispatch would admit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.context import ToolContext
from .mcp_capability_decisions import (
    McpCapabilityDecision,
    blocked_mcp_capability_discovery_result,
    decide_mcp_capability,
)
from .mcp_capability_gate import McpCapabilityRef, _approval_subject, _unverifiable_context_decision
from .mcp_governance.capability_policy import load_mcp_capability_index
from .mcp_workspace_context import resolve_workspace_context
from .tool_approval.rules import tool_approval_requirement


@dataclass(frozen=True, slots=True)
class McpCapabilityListing:
    visible: tuple[tuple[Any, McpCapabilityDecision, bool], ...] = ()
    blocked_result: dict[str, Any] | None = None
    blocked_reason: str | None = None


async def governed_mcp_capability_listing(
    context: ToolContext,
    *,
    server_name: str,
    tools: list[Any],
) -> McpCapabilityListing:
    # An unverifiable context gets the same named denial dispatch would return, never an empty success.
    resolution = resolve_workspace_context(context)
    if context.db is None or not resolution.resolved:
        decision = _unverifiable_context_decision(context, resolution, server_name=server_name, tool_name="")
        return McpCapabilityListing(
            blocked_result=blocked_mcp_capability_discovery_result(decision),
            blocked_reason=decision.reason,
        )
    index = await load_mcp_capability_index(context.db, workspace_id=resolution.workspace_id)
    visible: list[tuple[Any, McpCapabilityDecision, bool]] = []
    for tool in tools:
        decision = decide_mcp_capability(index, server_name=server_name, tool_name=str(getattr(tool, "name", "")))
        if not decision.allowed:
            continue
        subject = _approval_subject(
            McpCapabilityRef(server_name=decision.server_name, tool_name=decision.tool_name, arguments={}),
            decision,
        )
        requirement = tool_approval_requirement(subject.subject_key, context.project_config, subject=subject)
        visible.append((tool, decision, requirement.required))
    return McpCapabilityListing(visible=tuple(visible))


__all__ = ["McpCapabilityListing", "governed_mcp_capability_listing"]
