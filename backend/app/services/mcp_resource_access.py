"""The pre-transport check for MCP resource and prompt access.

``governed_mcp_resource_access`` is the last thing that runs before ``connect()``.
It enforces the whole decision, not only policy: canonical server identity, then
the binding decision, then the approval gate, using the shared primitives in
``mcp_resource_gate``. A request registry dispatch already governed is recognised
by the mark it left on the ToolContext and is not approved twice.

An admitted access is returned un-audited; the calling tool records the outcome it
actually observed through ``record_mcp_resource_execution``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..tools.context import ToolContext
from .mcp_resource_audit import (
    DISPATCH_OUT_OF_BAND,
    DISPATCH_TOOL,
    OUTCOME_AWAITING_APPROVAL,
    OUTCOME_DENIED,
)
from .mcp_resource_decision import McpResourceDecision, blocked_mcp_resource_result
from .mcp_resource_gate import (
    McpResourceRef,
    annotate_lost_governance_audit,
    audit_mcp_resource_decision,
    decide_mcp_resource_for_context,
    enforcement_mark,
    mcp_resource_approval_subject,
)
from .mcp_resource_identity import canonical_mcp_server_identity
from .mcp_resource_policy import denied_mcp_resource_decision
from .mcp_workspace_context import resolve_workspace_context
from .tool_approval_gate import enforce_tool_approval


@dataclass(frozen=True, slots=True)
class McpResourceAccess:
    """The last governance check before transport, plus the identity to call with.

    An admitted access is deliberately **not** audited yet: it carries the
    decision, the workspace, and the dispatch path it was admitted under so the
    calling tool can record what actually happened once the remote call has been
    attempted (``record_mcp_resource_execution``).
    """

    blocked_result: dict[str, Any] | None = None
    governed_identity: str = ""
    canonical_server_name: str = ""
    decision: McpResourceDecision | None = None
    workspace_id: str = ""
    dispatch: str = DISPATCH_OUT_OF_BAND


def _consume_enforcement_mark(context: ToolContext, mark: str) -> bool:
    """Consume the registry's "already governed and approved" mark, once."""
    marks = getattr(context, "enforced_approval_fingerprints", None)
    if not isinstance(marks, set) or mark not in marks:
        return False
    marks.discard(mark)
    return True


async def _denied_access(
    context: ToolContext,
    decision: McpResourceDecision,
    *,
    workspace_id: str,
    tool_name: str,
) -> McpResourceAccess:
    """Audit a denial before transport and return it as the blocked result."""
    recorded = await audit_mcp_resource_decision(
        context,
        decision,
        workspace_id=workspace_id,
        dispatch=DISPATCH_OUT_OF_BAND,
        tool_name=tool_name,
        outcome=OUTCOME_DENIED,
    )
    return McpResourceAccess(
        blocked_result=annotate_lost_governance_audit(blocked_mcp_resource_result(decision), recorded)
    )


async def _admitted_or_awaiting_approval(
    context: ToolContext,
    decision: McpResourceDecision,
    *,
    kind: str,
    canonical_server: str,
    workspace_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> McpResourceAccess:
    """An allowed decision still needs approval, unless registry dispatch already gave it."""
    ref = McpResourceRef(
        kind=kind,
        server_name=decision.server_name,
        identity=decision.identity,
        arguments=arguments if isinstance(arguments, dict) else {},
    )
    subject = mcp_resource_approval_subject(ref, decision)
    admitted = McpResourceAccess(
        governed_identity=decision.governed_identity,
        canonical_server_name=canonical_server,
        decision=decision,
        workspace_id=workspace_id,
        dispatch=DISPATCH_OUT_OF_BAND,
    )
    if _consume_enforcement_mark(context, enforcement_mark(subject)):
        # Registry dispatch governed and approved this exact request, so its row
        # belongs to that dispatch path rather than to this re-check.
        return replace(admitted, dispatch=DISPATCH_TOOL)

    approval_block = await enforce_tool_approval(tool_name, ref.approval_payload, context, subject=subject)
    if approval_block is not None:
        recorded = await audit_mcp_resource_decision(
            context,
            decision,
            workspace_id=workspace_id,
            dispatch=DISPATCH_OUT_OF_BAND,
            tool_name=tool_name,
            outcome=OUTCOME_AWAITING_APPROVAL,
        )
        return McpResourceAccess(blocked_result=annotate_lost_governance_audit(approval_block, recorded))
    return admitted


async def governed_mcp_resource_access(
    context: ToolContext,
    *,
    kind: str,
    server_name: str,
    identity: str,
    tool_name: str,
    configured_server_names: Sequence[str] = (),
    arguments: dict[str, Any] | None = None,
) -> McpResourceAccess:
    """Full governance immediately before a remote call, with the identity to use.

    Server identity, then the binding decision, then approval — in that order, so
    a direct execution that never went through registry dispatch reaches the
    remote server under exactly the same rules. When registry dispatch already
    enforced this precise request its mark is consumed here and the approval is
    not repeated, which is what keeps one request at one grant.

    Nothing is audited for an admitted access. The caller records the outcome it
    observed through ``record_mcp_resource_execution``, so an access that is
    admitted and then fails to connect is never recorded as an execution.
    """
    resolution = resolve_workspace_context(context)
    canonical_server, identity_state = canonical_mcp_server_identity(configured_server_names, server_name)
    if identity_state:
        # The governed catalog is keyed by the canonical server identity while
        # the transport is keyed by a configured name. No configured server owns
        # this identity, or several do — either way the platform cannot say which
        # remote server the catalog entry describes, so nothing may connect.
        decision = denied_mcp_resource_decision(
            kind=kind,
            server_name=server_name,
            identity=identity,
            state=identity_state,
            matched_rule="configured_server_identity",
        )
        return await _denied_access(context, decision, workspace_id=resolution.workspace_id, tool_name=tool_name)

    decision, resolution = await decide_mcp_resource_for_context(
        context, kind=kind, server_name=canonical_server, identity=identity
    )
    if not decision.allowed:
        return await _denied_access(context, decision, workspace_id=resolution.workspace_id, tool_name=tool_name)
    return await _admitted_or_awaiting_approval(
        context,
        decision,
        kind=kind,
        canonical_server=canonical_server,
        workspace_id=resolution.workspace_id,
        tool_name=tool_name,
        arguments=arguments,
    )


async def record_mcp_resource_execution(
    context: ToolContext,
    access: McpResourceAccess,
    *,
    tool_name: str,
    outcome: str,
) -> bool:
    """Record what an admitted governed request actually did.

    This is the only writer that may record ``executed_allowed``, and it runs
    after the remote call has been attempted. An access that was never admitted
    carries no decision and was already audited where it was refused, so calling
    this for one is a no-op. ``False`` means the evidence was lost and the caller
    must say so on its result.
    """
    if access.decision is None:
        return True
    return await audit_mcp_resource_decision(
        context,
        access.decision,
        workspace_id=access.workspace_id,
        dispatch=access.dispatch,
        tool_name=tool_name,
        outcome=outcome,
    )


__all__ = [
    "McpResourceAccess",
    "governed_mcp_resource_access",
    "record_mcp_resource_execution",
]
