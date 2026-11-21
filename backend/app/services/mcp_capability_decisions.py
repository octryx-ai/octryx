"""Decisions and blocked results for mirrored MCP capabilities.

The rules are described in ``mcp_capability_policy``, which owns the catalog keys
and loads a workspace's mirrored capability index; this module turns that index
into the one decision dispatch and discovery share, and into the secret-free
payload a denied capability answers with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .mcp_capability_policy import (
    _HIDDEN_BINDING_STATUS,
    DEFAULT_MCP_CAPABILITY_RISK,
    MCP_CAPABILITY_POLICY_NAME,
    MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW,
    McpCapabilityIndex,
    MirroredMcpCapability,
    load_mcp_capability_index,
    mcp_capability_binding_key,
    mcp_capability_subject_key,
)


@dataclass(frozen=True, slots=True)
class McpCapabilityDecision:
    server_name: str
    tool_name: str
    allowed: bool
    reason: str
    risk: str
    matched_rule: str
    capability_state: str
    scopes: tuple[str, ...] = ()

    @property
    def subject_key(self) -> str:
        return mcp_capability_subject_key(self.server_name, self.tool_name)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "capability_key": mcp_capability_binding_key(self.server_name, self.tool_name),
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "scopes": list(self.scopes),
            "matched_rule": self.matched_rule,
            "capability_state": self.capability_state,
        }


def unverifiable_mcp_capability_decision(
    server_name: str,
    tool_name: str,
    *,
    reason: str = "missing_workspace_context",
    matched_rule: str = "unverifiable_context",
) -> McpCapabilityDecision:
    """Missing database or unresolvable workspace context denies.

    ``reason``/``matched_rule`` name *why* the context was unverifiable — no
    database session, no project id at all, or several ambiguous ones.
    """
    return McpCapabilityDecision(
        server_name=str(server_name or "").strip(),
        tool_name=str(tool_name or "").strip(),
        allowed=False,
        reason=str(reason or "").strip() or "missing_workspace_context",
        risk=DEFAULT_MCP_CAPABILITY_RISK,
        matched_rule=str(matched_rule or "").strip() or "unverifiable_context",
        capability_state="unverifiable",
    )


def _unbound_decision(normalized_server: str, normalized_tool: str) -> McpCapabilityDecision:
    """No Workspace Capability binding: denied. A tool becomes usable only once an admin enables its binding."""
    return McpCapabilityDecision(
        server_name=normalized_server,
        tool_name=normalized_tool,
        allowed=False,
        reason="mcp_capability_not_bound",
        risk=DEFAULT_MCP_CAPABILITY_RISK,
        matched_rule="no_workspace_capability_binding",
        capability_state="unbound",
    )


def _bound_decision(
    capability: MirroredMcpCapability, normalized_server: str, normalized_tool: str
) -> McpCapabilityDecision:
    """A mirrored binding allows only while enabled, visible, active and not waiting for review."""
    if not capability.capability_type_active:
        return McpCapabilityDecision(
            server_name=normalized_server,
            tool_name=normalized_tool,
            allowed=False,
            reason="mcp_capability_type_inactive",
            risk=capability.risk,
            matched_rule="capability_type_lifecycle",
            capability_state="bound",
            scopes=capability.scopes,
        )
    if capability.review_state == MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW:
        return McpCapabilityDecision(
            server_name=normalized_server,
            tool_name=normalized_tool,
            allowed=False,
            reason="mcp_capability_schema_drift",
            risk=capability.risk,
            matched_rule="schema_drift_needs_review",
            capability_state="needs_review",
            scopes=capability.scopes,
        )
    if not capability.is_enabled or capability.binding_status == _HIDDEN_BINDING_STATUS:
        return McpCapabilityDecision(
            server_name=normalized_server,
            tool_name=normalized_tool,
            allowed=False,
            reason="mcp_capability_disabled",
            risk=capability.risk,
            matched_rule=(
                "binding_status_hidden" if capability.binding_status == _HIDDEN_BINDING_STATUS else "binding_disabled"
            ),
            capability_state="bound",
            scopes=capability.scopes,
        )
    return McpCapabilityDecision(
        server_name=normalized_server,
        tool_name=normalized_tool,
        allowed=True,
        reason="mcp_capability_enabled",
        risk=capability.risk,
        matched_rule="workspace_capability_binding",
        capability_state="bound",
        scopes=capability.scopes,
    )


def decide_mcp_capability(
    index: McpCapabilityIndex,
    *,
    server_name: str,
    tool_name: str,
) -> McpCapabilityDecision:
    """Return the single authoritative decision shared by dispatch and discovery."""
    normalized_server = str(server_name or "").strip()
    normalized_tool = str(tool_name or "").strip()
    if not normalized_server or not normalized_tool:
        return McpCapabilityDecision(
            server_name=normalized_server,
            tool_name=normalized_tool,
            allowed=False,
            reason="missing_capability_identity",
            risk=DEFAULT_MCP_CAPABILITY_RISK,
            matched_rule="invalid_request",
            capability_state="unverifiable",
        )

    capability = index.get(normalized_server, normalized_tool)
    if capability is None:
        return _unbound_decision(normalized_server, normalized_tool)
    return _bound_decision(capability, normalized_server, normalized_tool)


async def mcp_capability_decision(
    db: AsyncSession | None,
    *,
    workspace_id: str | None,
    server_name: str,
    tool_name: str,
) -> McpCapabilityDecision:
    """Resolve one capability decision, denying when the workspace is unverifiable."""
    normalized_workspace_id = str(workspace_id or "").strip()
    if db is None or not normalized_workspace_id:
        return unverifiable_mcp_capability_decision(server_name, tool_name)
    index = await load_mcp_capability_index(db, workspace_id=normalized_workspace_id)
    return decide_mcp_capability(index, server_name=server_name, tool_name=tool_name)


def _blocked_capability_message(decision: McpCapabilityDecision) -> str:
    subject = f"MCP capability '{decision.tool_name}' on server '{decision.server_name}'"
    if decision.reason == "mcp_capability_schema_drift":
        return (
            f"{subject} changed its argument contract since it was approved and needs review. "
            "Re-enable it in the Workspace capability catalog to accept the new contract."
        )
    return f"{subject} is not enabled for this workspace. Enable it in the Workspace capability catalog."


def blocked_mcp_capability_result(decision: McpCapabilityDecision) -> dict[str, Any]:
    """Uniform, secret-free tool-result payload for a denied MCP capability."""
    return {
        "error": _blocked_capability_message(decision),
        "mcp_server": decision.server_name,
        "mcp_capability": decision.tool_name,
        "blocked_by": MCP_CAPABILITY_POLICY_NAME,
        "reason": decision.reason,
        "capability_decision": decision.to_metadata(),
    }


def blocked_mcp_capability_discovery_result(decision: McpCapabilityDecision) -> dict[str, Any]:
    """Explicit blocked result for capability discovery that cannot be decided.

    Discovery must never answer an unverifiable context with an empty but
    successful listing: ``connected=true`` plus ``count=0`` is indistinguishable
    from "this server legitimately exposes nothing". The caller gets a named,
    auditable denial instead.
    """
    return {
        "error": (
            f"MCP capability governance for server '{decision.server_name}' cannot be verified in this "
            "execution context, so capability discovery is blocked."
        ),
        "mcp_server": decision.server_name,
        "blocked_by": MCP_CAPABILITY_POLICY_NAME,
        "reason": decision.reason,
        "capability_decision": decision.to_metadata(),
    }


__all__ = [
    "McpCapabilityDecision",
    "blocked_mcp_capability_discovery_result",
    "blocked_mcp_capability_result",
    "decide_mcp_capability",
    "mcp_capability_decision",
    "unverifiable_mcp_capability_decision",
]
