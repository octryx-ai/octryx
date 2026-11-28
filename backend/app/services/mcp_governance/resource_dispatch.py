"""Registry-dispatch governance of the MCP resource and prompt bridge tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...tools.context import ToolContext
from ..mcp_access_policy import blocked_mcp_server_result, mcp_access_for_context
from ..tool_approval.rules import ToolApprovalSubject
from .resource_audit import DISPATCH_TOOL, OUTCOME_AWAITING_APPROVAL, OUTCOME_DENIED
from .resource_decision import McpResourceDecision, blocked_mcp_resource_result
from .resource_gate import (
    McpResourceRef,
    audit_mcp_resource_decision,
    decide_mcp_resource_for_context,
    enforcement_mark,
    mcp_resource_approval_subject,
    resolve_mcp_resource_ref,
)
from .resource_identity import MCP_RESOURCE_POLICY_NAME


@dataclass(frozen=True, slots=True)
class McpResourceGateOutcome:
    ref: McpResourceRef | None = None
    decision: McpResourceDecision | None = None
    workspace_id: str = ""
    blocked_result: dict[str, Any] | None = None
    blocked_policy: str | None = None
    blocked_reason: str | None = None
    approval_subject: ToolApprovalSubject | None = None


async def evaluate_mcp_resource_dispatch(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
) -> McpResourceGateOutcome:
    # One final outcome row per dispatch: a denial is audited here; for an allow, finalize audits a hold or a later
    # block, and the tool records the outcome only after its transport attempt.
    ref = resolve_mcp_resource_ref(tool_name, params)
    if ref is None:
        return McpResourceGateOutcome()

    access = mcp_access_for_context(ref.server_name, context)
    if not access.allowed:
        return McpResourceGateOutcome(
            ref=ref,
            blocked_result=blocked_mcp_server_result(access),
            blocked_policy="mcp_access_policy",
            blocked_reason=access.reason,
        )

    decision, resolution = await decide_mcp_resource_for_context(
        context,
        kind=ref.kind,
        server_name=ref.server_name,
        identity=ref.identity,
    )
    if not decision.allowed:
        await audit_mcp_resource_decision(
            context,
            decision,
            workspace_id=resolution.workspace_id,
            dispatch=DISPATCH_TOOL,
            tool_name=tool_name,
            outcome=OUTCOME_DENIED,
        )
        return McpResourceGateOutcome(
            ref=ref,
            decision=decision,
            workspace_id=resolution.workspace_id,
            blocked_result=blocked_mcp_resource_result(decision),
            blocked_policy=MCP_RESOURCE_POLICY_NAME,
            blocked_reason=decision.public_reason,
        )
    return McpResourceGateOutcome(
        ref=ref,
        decision=decision,
        workspace_id=resolution.workspace_id,
        approval_subject=mcp_resource_approval_subject(ref, decision),
    )


async def finalize_mcp_resource_dispatch(
    outcome: McpResourceGateOutcome,
    context: ToolContext,
    *,
    tool_name: str,
    approval_held: bool,
    blocked_downstream: bool = False,
) -> None:
    # A proceed is not final, so nothing is audited for it here: ``executed_allowed`` is never written before anything
    # executed.
    decision = outcome.decision
    if decision is None or not decision.allowed:
        return
    if approval_held or blocked_downstream:
        await audit_mcp_resource_decision(
            context,
            decision,
            workspace_id=outcome.workspace_id,
            dispatch=DISPATCH_TOOL,
            tool_name=tool_name,
            outcome=OUTCOME_AWAITING_APPROVAL if approval_held else OUTCOME_DENIED,
        )
        return
    if outcome.approval_subject is not None:
        marks = getattr(context, "enforced_approval_fingerprints", None)
        if isinstance(marks, set):
            marks.add(enforcement_mark(outcome.approval_subject))


__all__ = [
    "McpResourceGateOutcome",
    "evaluate_mcp_resource_dispatch",
    "finalize_mcp_resource_dispatch",
]
