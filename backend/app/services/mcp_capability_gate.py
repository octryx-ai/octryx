"""One authoritative MCP capability gate for dispatch and discovery. Every path to an MCP tool resolves through it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.context import ToolContext
from .mcp_access_policy import blocked_mcp_server_result, mcp_access_for_context
from .mcp_capability_decisions import (
    McpCapabilityDecision,
    blocked_mcp_capability_result,
    decide_mcp_capability,
    unverifiable_mcp_capability_decision,
)
from .mcp_governance.capability_policy import load_mcp_capability_index, mcp_capability_subject_key
from .mcp_workspace_context import WorkspaceContextResolution, resolve_workspace_context
from .tool_approval.gate import enforce_tool_approval
from .tool_approval.rules import ToolApprovalSubject

MCP_BRIDGE_CALL_TOOL_NAME = "call_mcp_server_tool"
_MCP_FQN_PREFIX = "mcp__"


@dataclass(frozen=True, slots=True)
class McpCapabilityRef:
    server_name: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class McpCapabilityGateOutcome:
    ref: McpCapabilityRef | None = None
    decision: McpCapabilityDecision | None = None
    blocked_result: dict[str, Any] | None = None
    blocked_policy: str | None = None
    blocked_reason: str | None = None
    approval_subject: ToolApprovalSubject | None = None


def resolve_mcp_capability_ref(tool_name: str, params: dict[str, Any] | None) -> McpCapabilityRef | None:
    normalized_tool = str(tool_name or "").strip()
    payload = params if isinstance(params, dict) else {}
    if normalized_tool == MCP_BRIDGE_CALL_TOOL_NAME:
        arguments = payload.get("arguments")
        return McpCapabilityRef(
            server_name=str(payload.get("server_name") or "").strip(),
            tool_name=str(payload.get("tool_name") or "").strip(),
            arguments=arguments if isinstance(arguments, dict) else {},
        )
    if normalized_tool.startswith(_MCP_FQN_PREFIX):
        parts = normalized_tool.split("__", 2)
        if len(parts) != 3:
            return None
        return McpCapabilityRef(server_name=parts[1].strip(), tool_name=parts[2].strip(), arguments=dict(payload))
    return None


def _approval_subject(ref: McpCapabilityRef, decision: McpCapabilityDecision) -> ToolApprovalSubject:
    return ToolApprovalSubject(
        subject_key=mcp_capability_subject_key(ref.server_name, ref.tool_name),
        risk=decision.risk,
        display_name=f"MCP capability {ref.server_name}/{ref.tool_name}",
        payload=ref.arguments,
        details=(
            f"mcp server: {ref.server_name}",
            f"mcp capability: {ref.tool_name}",
            f"capability rule: {decision.matched_rule}",
        ),
    )


def _unverifiable_context_decision(
    context: ToolContext,
    resolution: WorkspaceContextResolution,
    *,
    server_name: str,
    tool_name: str,
) -> McpCapabilityDecision:
    if context.db is None:
        return unverifiable_mcp_capability_decision(server_name, tool_name, matched_rule="missing_database_context")
    return unverifiable_mcp_capability_decision(
        server_name,
        tool_name,
        reason=resolution.reason,
        matched_rule=resolution.matched_rule,
    )


async def _capability_decision_for_context(
    context: ToolContext,
    *,
    server_name: str,
    tool_name: str,
) -> McpCapabilityDecision:
    resolution = resolve_workspace_context(context)
    if context.db is None or not resolution.resolved:
        return _unverifiable_context_decision(context, resolution, server_name=server_name, tool_name=tool_name)
    index = await load_mcp_capability_index(context.db, workspace_id=resolution.workspace_id)
    return decide_mcp_capability(index, server_name=server_name, tool_name=tool_name)


async def evaluate_mcp_capability_ref(
    ref: McpCapabilityRef,
    context: ToolContext,
) -> McpCapabilityGateOutcome:
    access = mcp_access_for_context(ref.server_name, context)
    if not access.allowed:
        return McpCapabilityGateOutcome(
            ref=ref,
            blocked_result=blocked_mcp_server_result(access),
            blocked_policy="mcp_access_policy",
            blocked_reason=access.reason,
        )

    decision = await _capability_decision_for_context(
        context,
        server_name=ref.server_name,
        tool_name=ref.tool_name,
    )
    if not decision.allowed:
        return McpCapabilityGateOutcome(
            ref=ref,
            decision=decision,
            blocked_result=blocked_mcp_capability_result(decision),
            blocked_policy="mcp_capability_policy",
            blocked_reason=decision.reason,
        )
    # Imported lazily: the run capability module pulls in workflow decision services.
    from .run_capability.escalation import CAPABILITY_REFUSAL_POLICY, mcp_capability_dispatch_refusal

    refusal = mcp_capability_dispatch_refusal(
        mcp_capability_subject_key(ref.server_name, ref.tool_name),
        decision.server_name or ref.server_name,
        decision.tool_name or ref.tool_name,
        decision.risk, context,
    )
    if refusal is not None:
        return McpCapabilityGateOutcome(
            ref=ref,
            decision=decision,
            blocked_result=refusal,
            blocked_policy=CAPABILITY_REFUSAL_POLICY,
            blocked_reason="capability_exceeded",
        )
    return McpCapabilityGateOutcome(ref=ref, decision=decision, approval_subject=_approval_subject(ref, decision))


async def evaluate_mcp_capability_dispatch(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
) -> McpCapabilityGateOutcome:
    ref = resolve_mcp_capability_ref(tool_name, params)
    if ref is None:
        return McpCapabilityGateOutcome()
    return await evaluate_mcp_capability_ref(ref, context)


async def enforce_remote_mcp_capability(
    *,
    dispatch_tool_name: str,
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    context: ToolContext,
) -> dict[str, Any] | None:
    # Tools that reach an MCP server themselves run this same decision; a non-``None`` result is returned instead of
    # calling the server.
    ref = McpCapabilityRef(
        server_name=str(server_name or "").strip(),
        tool_name=str(tool_name or "").strip(),
        arguments=arguments if isinstance(arguments, dict) else {},
    )
    outcome = await evaluate_mcp_capability_ref(ref, context)
    if outcome.blocked_result is not None:
        # Imported lazily: the tool result layer imports the tool definitions,
        # which must not be pulled in while the registry is being built.
        from ..tools.results import annotate_tool_result_payload

        return annotate_tool_result_payload(
            dispatch_tool_name,
            outcome.blocked_result,
            category="denied_by_policy",
            reason=outcome.blocked_reason,
            policy=outcome.blocked_policy,
        )
    return await enforce_tool_approval(
        dispatch_tool_name,
        ref.arguments,
        context,
        subject=outcome.approval_subject,
    )


async def mcp_capability_dispatch_block(
    *,
    server_name: str,
    tool_name: str,
    context: ToolContext,
) -> dict[str, Any] | None:
    decision = await _capability_decision_for_context(context, server_name=server_name, tool_name=tool_name)
    if decision.allowed:
        return None
    return blocked_mcp_capability_result(decision)


__all__ = [
    "MCP_BRIDGE_CALL_TOOL_NAME",
    "McpCapabilityGateOutcome",
    "McpCapabilityRef",
    "enforce_remote_mcp_capability",
    "evaluate_mcp_capability_dispatch",
    "evaluate_mcp_capability_ref",
    "mcp_capability_dispatch_block",
    "resolve_mcp_capability_ref",
]
