"""Registry-dispatch governance for the MCP resource and prompt bridge tools.

``tools/registry.py`` runs one governance path for every tool call. This module is
the MCP resource/prompt half of it: it maps a dispatch request onto the governed
item it addresses, evaluates server activation and the workspace binding, and
hands the registry an explicit per-item approval subject.

The split from ``mcp_resource_gate`` is the split between the two entry points.
Everything shared — the reference, the index, the decision, the approval subject,
the audit helper, the enforcement mark — stays in the gate, so the registry path
and the pre-transport path cannot disagree; only the sequencing lives here.

Sequencing is the whole point of this module:

- a **denial** is final at this point, so it is audited immediately;
- an **allow** is not. The approval gate still runs, and after it the tool still
  has to reach a remote server. A hold is audited here as
  ``allowed_awaiting_approval``; a proceed is audited by the tool once the remote
  call has been attempted, never here. Nothing on this path can therefore record
  an execution that did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.context import ToolContext
from .mcp_access_policy import blocked_mcp_server_result, mcp_access_for_context
from .mcp_resource_audit import DISPATCH_TOOL, OUTCOME_AWAITING_APPROVAL, OUTCOME_DENIED
from .mcp_resource_decision import McpResourceDecision, blocked_mcp_resource_result
from .mcp_resource_gate import (
    McpResourceRef,
    audit_mcp_resource_decision,
    decide_mcp_resource_for_context,
    enforcement_mark,
    mcp_resource_approval_subject,
    resolve_mcp_resource_ref,
)
from .mcp_resource_identity import MCP_RESOURCE_POLICY_NAME
from .tool_approval_rules import ToolApprovalSubject


@dataclass(frozen=True, slots=True)
class McpResourceGateOutcome:
    """Either a blocking payload or the approval subject for an admitted item."""

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
    """Evaluate one registry dispatch; a non-resource tool yields an empty outcome.

    A denial is final here and is audited immediately. An allow is *not* final —
    the approval gate still runs — so it is audited by
    ``finalize_mcp_resource_dispatch`` once the approval answer exists.
    """
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
    """Close out an admitted dispatch: audit a hold or a block, or mark a proceed.

    A hold is final — nothing will execute — so it is audited here as
    ``allowed_awaiting_approval``, and so is a request a later gate refused
    (``denied``). A proceed is **not** final: the tool still has to reach the
    remote server, the pre-transport re-check can deny on a policy change, and
    the transport can be unavailable. So nothing is audited for it here; the
    request is only marked as already governed, and the tool records the outcome
    it observes. That is what keeps ``executed_allowed`` from being written
    before anything executed, and keeps one governed request at one row.
    """
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
