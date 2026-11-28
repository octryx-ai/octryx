"""Governance primitives shared by registry dispatch, the pre-transport check and discovery of MCP resources
and prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...tools.context import ToolContext
from ..change_preview import build_change_request_fingerprint
from ..mcp_workspace_context import WorkspaceContextResolution, resolve_workspace_context
from ..tool_approval.rules import ToolApprovalSubject
from .resource_arguments import MCP_RESOURCE_ID_PARAM
from .resource_audit import (
    GOVERNANCE_AUDIT_KEY,
    GOVERNANCE_AUDIT_UNAVAILABLE,
    record_mcp_resource_decision,
)
from .resource_decision import McpResourceDecision
from .resource_identity import (
    MCP_PROMPT_GET_TOOL,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_READ_TOOL,
    mcp_resource_kind_label,
    normalized_mcp_prompt_identity,
    normalized_mcp_resource_identity,
    normalized_scope_tags,
)
from .resource_index import McpResourceIndex, load_mcp_resource_index
from .resource_policy import decide_mcp_resource, unverifiable_mcp_resource_decision
from .resource_states import STATE_MISSING_DATABASE, STATE_MISSING_USER


@dataclass(frozen=True, slots=True)
class McpResourceRef:
    kind: str
    server_name: str
    identity: str
    arguments: dict[str, Any]

    @property
    def approval_payload(self) -> dict[str, Any]:
        # Never a URI.
        if self.kind == MCP_PROMPT_KIND:
            return {"prompt_name": self.identity, "arguments": self.arguments}
        return {MCP_RESOURCE_ID_PARAM: self.identity}


def resolve_mcp_resource_ref(tool_name: str, params: dict[str, Any] | None) -> McpResourceRef | None:
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
    return normalized_scope_tags(
        [
            str(getattr(context, "capability_type", "") or ""),
            str(getattr(context, "agent_mode_key", "") or ""),
        ]
    )


def missing_user_context(context: ToolContext) -> bool:
    # No user means no audit row and nobody to ask for approval, so it denies before transport, whatever the risk.
    return not str(getattr(context, "user_id", "") or "").strip()


def unverifiable_decision_for(
    context: ToolContext,
    resolution: WorkspaceContextResolution,
    *,
    kind: str,
    server_name: str,
    identity: str = "",
) -> McpResourceDecision:
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
    resolution = resolve_workspace_context(context)
    if context.db is None or not resolution.resolved or missing_user_context(context):
        return None, resolution
    return await load_mcp_resource_index(context.db, workspace_id=resolution.workspace_id), resolution


def mcp_resource_approval_subject(ref: McpResourceRef, decision: McpResourceDecision) -> ToolApprovalSubject:
    # Shared by every path.
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
    # Carried on the payload, so an operator can tell this request left no evidence.
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
