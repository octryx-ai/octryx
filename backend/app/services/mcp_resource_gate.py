"""The shared governance primitives for MCP resource and prompt access.

Three paths can reach a governed resource or prompt, and all three resolve
through the helpers here so none of them can disagree with another:

- registry dispatch (``services/mcp_resource_dispatch.py``), which evaluates the
  request and hands the registry an explicit per-item approval subject;
- the pre-transport check ``governed_mcp_resource_access``
  (``services/mcp_resource_access.py``), which is the last thing that runs
  before ``connect()``;
- discovery (``services/mcp_resource_discovery.py``), which answers from the same
  index and the same decision function and opens no connection at all.

**The pre-transport check enforces the whole decision, not only policy.** A tool
executed outside registry dispatch reaches ``governed_mcp_resource_access``, and
that call resolves the server identity, runs the binding decision, *and* runs the
approval gate before any ``connect()``. There is therefore no supported path on
which a direct execution reaches a remote server with less governance than
registry dispatch applied.

Registry dispatch marks the request it already enforced on the ToolContext
(``enforced_approval_fingerprints``), keyed by the approval subject and its
payload. The pre-transport check consumes that mark exactly once, which is what
keeps one governed request at one approval grant and one audit row instead of
two. A request with no mark — a direct execution — is governed from scratch.

Evaluation order is fixed:

1. project MCP **server** activation (``services/mcp_access_policy.py``);
2. **canonical server identity**: the governed catalog is keyed by the casefolded
   server name while the transport is keyed by a configured one, so exactly one
   configured server must own the identity. Zero or several deny before connect,
   which is what stops ``DEMO`` from retargeting ``demo``'s governed catalog
   entry at a different remote server;
3. workspace **item** governance (``services/mcp_resource_policy.py``);
4. the existing project approval policy, given an explicit ``ToolApprovalSubject``
   so the approval identity is server + item + arguments instead of the generic
   bridge tool name.

Workspace resolution is shared with the mirrored-tool gate
(``mcp_workspace_context.resolve_workspace_context``): server-owned context only,
never a model-supplied argument, and zero or several competing project ids stay
unverifiable and deny. A context with no user id is unverifiable too — there is
nobody to ask for approval and nobody to attribute an audit row to — so it denies
explicitly rather than executing unaudited, whatever the item's risk.

Execution scope comes from the run's own server-owned identity
(``ToolContext.capability_type`` and ``ToolContext.agent_mode_key``). A binding
with an empty ``intent_scopes`` is unrestricted; a non-empty one only matches a
run whose scope is listed.

Nothing here reads MCP connection configuration — the configured server *names*
are passed in by the caller that owns the transport — and nothing here accepts a
resource URI: a read addresses the opaque catalog identity discovery published,
so no environment, header, OAuth, or credential material can reach a result
payload or a persisted argument.

Nothing here records an execution either. An admitted access is returned
un-audited, carrying the decision it was admitted under, and the calling tool
records the outcome it actually observed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.context import ToolContext
from .change_preview import build_change_request_fingerprint
from .mcp_resource_arguments import MCP_RESOURCE_ID_PARAM
from .mcp_resource_audit import (
    GOVERNANCE_AUDIT_KEY,
    GOVERNANCE_AUDIT_UNAVAILABLE,
    record_mcp_resource_decision,
)
from .mcp_resource_decision import McpResourceDecision
from .mcp_resource_identity import (
    MCP_PROMPT_GET_TOOL,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_READ_TOOL,
    mcp_resource_kind_label,
    normalized_mcp_prompt_identity,
    normalized_mcp_resource_identity,
    normalized_scope_tags,
)
from .mcp_resource_index import McpResourceIndex, load_mcp_resource_index
from .mcp_resource_policy import decide_mcp_resource, unverifiable_mcp_resource_decision
from .mcp_resource_states import STATE_MISSING_DATABASE, STATE_MISSING_USER
from .mcp_workspace_context import WorkspaceContextResolution, resolve_workspace_context
from .tool_approval_rules import ToolApprovalSubject


@dataclass(frozen=True, slots=True)
class McpResourceRef:
    """The governed item a request addresses, independent of the path used."""

    kind: str
    server_name: str
    identity: str
    arguments: dict[str, Any]

    @property
    def approval_payload(self) -> dict[str, Any]:
        """The argument payload an approval grant is bound to (never a URI)."""
        if self.kind == MCP_PROMPT_KIND:
            return {"prompt_name": self.identity, "arguments": self.arguments}
        return {MCP_RESOURCE_ID_PARAM: self.identity}


def resolve_mcp_resource_ref(tool_name: str, params: dict[str, Any] | None) -> McpResourceRef | None:
    """Map a dispatch request onto the governed item it addresses, or ``None``."""
    normalized_tool = str(tool_name or "").strip()
    payload = params if isinstance(params, dict) else {}
    server_name = str(payload.get("server_name") or "").strip()
    if normalized_tool == MCP_RESOURCE_READ_TOOL:
        # The opaque catalog identity is the whole request. A ``uri`` the model
        # supplied anyway is not read here and never becomes addressable.
        return McpResourceRef(
            kind=MCP_RESOURCE_KIND,
            server_name=server_name,
            identity=normalized_mcp_resource_identity(payload.get(MCP_RESOURCE_ID_PARAM)),
            arguments={},
        )
    if normalized_tool == MCP_PROMPT_GET_TOOL:
        arguments = payload.get("arguments")
        return McpResourceRef(
            kind=MCP_PROMPT_KIND,
            server_name=server_name,
            # Bounded at ingest: a name the catalog could never key is not an
            # identity, and nothing unbounded reaches the decision or the audit.
            identity=normalized_mcp_prompt_identity(payload.get("prompt_name")),
            arguments=arguments if isinstance(arguments, dict) else {},
        )
    return None


def execution_scope_tags(context: ToolContext) -> frozenset[str]:
    """Return the run's server-owned execution scope tags for a scope check."""
    return normalized_scope_tags(
        [
            str(getattr(context, "capability_type", "") or ""),
            str(getattr(context, "agent_mode_key", "") or ""),
        ]
    )


def missing_user_context(context: ToolContext) -> bool:
    """Whether this context has no user identity, which is never decidable.

    ``AuditLog.user_id`` is ``nullable=False`` and the approval gate has nobody to
    ask, so a context without a user cannot produce governance evidence. An allow
    on such a context would be an unaudited allow, so it denies explicitly and
    before transport — including when the item's risk needs no approval at all.
    """
    return not str(getattr(context, "user_id", "") or "").strip()


def unverifiable_decision_for(
    context: ToolContext,
    resolution: WorkspaceContextResolution,
    *,
    kind: str,
    server_name: str,
    identity: str = "",
) -> McpResourceDecision:
    """Name why this context cannot be decided: no user, no database, no workspace."""
    if missing_user_context(context):
        state = STATE_MISSING_USER
    else:
        state = STATE_MISSING_DATABASE if context.db is None else resolution.reason
    return unverifiable_mcp_resource_decision(
        kind=kind,
        server_name=server_name,
        identity=identity,
        state=state,
    )


async def resolve_mcp_resource_index(
    context: ToolContext,
) -> tuple[McpResourceIndex | None, WorkspaceContextResolution]:
    """Load this context's governed catalog, or say why it cannot be loaded."""
    resolution = resolve_workspace_context(context)
    if context.db is None or not resolution.resolved or missing_user_context(context):
        return None, resolution
    return await load_mcp_resource_index(context.db, workspace_id=resolution.workspace_id), resolution


def mcp_resource_approval_subject(ref: McpResourceRef, decision: McpResourceDecision) -> ToolApprovalSubject:
    """Return the explicit per-item approval identity shared by every path."""
    noun = mcp_resource_kind_label(ref.kind)
    return ToolApprovalSubject(
        subject_key=decision.subject_key,
        risk=decision.risk,
        display_name=f"MCP {noun} {ref.server_name}/{ref.identity}",
        payload=ref.approval_payload,
        details=(
            f"mcp server: {ref.server_name}",
            f"mcp {noun}: {ref.identity}",
            f"{noun} rule: {decision.matched_rule}",
        ),
    )


async def audit_mcp_resource_decision(
    context: ToolContext,
    decision: McpResourceDecision,
    *,
    workspace_id: str,
    dispatch: str,
    tool_name: str,
    outcome: str,
) -> bool:
    """Record the one final-outcome governance row; ``False`` when it was lost."""
    return await record_mcp_resource_decision(
        context.db,
        decision=decision,
        workspace_id=workspace_id,
        user_id=str(context.user_id or ""),
        session_id=str(context.session_id or ""),
        dispatch=dispatch,
        tool_name=tool_name,
        outcome=outcome,
    )


async def decide_mcp_resource_for_context(
    context: ToolContext,
    *,
    kind: str,
    server_name: str,
    identity: str,
) -> tuple[McpResourceDecision, WorkspaceContextResolution]:
    """Resolve the one decision every resource/prompt path shares."""
    index, resolution = await resolve_mcp_resource_index(context)
    if index is None:
        return (
            unverifiable_decision_for(context, resolution, kind=kind, server_name=server_name, identity=identity),
            resolution,
        )
    return (
        decide_mcp_resource(
            index,
            kind=kind,
            server_name=server_name,
            identity=identity,
            scope_tags=execution_scope_tags(context),
        ),
        resolution,
    )


def enforcement_mark(subject: ToolApprovalSubject) -> str:
    return build_change_request_fingerprint(subject.subject_key, subject.payload or {})


def annotate_lost_governance_audit(result: dict[str, Any], recorded: bool) -> dict[str, Any]:
    """Mark a governed result whose audit row could not be written.

    The governance answer itself stands — a denial is still a denial and an
    execution still happened — but an operator must be able to tell that this
    request left no evidence, so the fact is carried on the payload instead of
    being swallowed with the failed insert.
    """
    if recorded:
        return result
    return {**result, GOVERNANCE_AUDIT_KEY: GOVERNANCE_AUDIT_UNAVAILABLE}


__all__ = [
    "McpResourceRef",
    "annotate_lost_governance_audit",
    "audit_mcp_resource_decision",
    "decide_mcp_resource_for_context",
    "enforcement_mark",
    "execution_scope_tags",
    "mcp_resource_approval_subject",
    "missing_user_context",
    "resolve_mcp_resource_index",
    "resolve_mcp_resource_ref",
    "unverifiable_decision_for",
]
