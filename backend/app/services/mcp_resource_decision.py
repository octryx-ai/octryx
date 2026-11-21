"""The decision on one MCP resource or prompt, and its uniform denial payload (``mcp_resource_policy``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mcp_resource_identity import (
    MCP_RESOURCE_POLICY_NAME,
    mcp_resource_kind_label,
    mcp_resource_subject_key,
)
from .mcp_resource_states import UNVERIFIABLE_STATES


@dataclass(frozen=True, slots=True)
class McpResourceDecision:
    """The single authoritative answer shared by discovery, read, and get."""

    kind: str
    server_name: str
    identity: str
    allowed: bool
    state: str
    risk: str
    matched_rule: str
    governed_identity: str = ""
    scopes: tuple[str, ...] = ()
    binding_key: str = ""

    @property
    def kind_label(self) -> str:
        return mcp_resource_kind_label(self.kind)

    @property
    def unverifiable(self) -> bool:
        return self.state in UNVERIFIABLE_STATES

    @property
    def public_reason(self) -> str:
        """The one model-visible reason code for this decision's family."""
        if self.unverifiable:
            return f"mcp_{self.kind_label}_governance_unverifiable"
        return f"mcp_{self.kind_label}_not_available"

    @property
    def subject_key(self) -> str:
        return mcp_resource_subject_key(self.kind, self.server_name, self.identity)

    def audit_metadata(self) -> dict[str, Any]:
        """Redaction-safe governance facts: opaque identity only.

        ``governed_identity`` is deliberately **absent**. For a resource it is the
        governed URI, and a governed URI is still a URI — an internal host, a
        bucket path, a database name. An audit row only needs to say *which
        catalog entry* was decided, and ``identity`` (the ``sha256`` digest) plus
        ``binding_key`` (which embeds that digest) say exactly that while an
        operator resolves the URI from the catalog. Nothing here is free text,
        nothing is model-supplied, and nothing is a URI.
        """
        return {
            "kind": self.kind,
            "server_name": self.server_name,
            "identity": self.identity,
            "binding_key": self.binding_key,
            "allowed": self.allowed,
            "state": self.state,
            "public_reason": self.public_reason,
            "risk": self.risk,
            "scopes": list(self.scopes),
            "matched_rule": self.matched_rule,
        }


def _denial_message(decision: McpResourceDecision) -> str:
    """One message for the whole denial family, so states stay indistinguishable."""
    noun = decision.kind_label
    if decision.unverifiable:
        return (
            f"MCP {noun} governance for server '{decision.server_name}' cannot be verified in this "
            f"execution context, so {noun} access is blocked."
        )
    return (
        f"The requested MCP {noun} is not available to this workspace on server "
        f"'{decision.server_name}'. Mirror it into the Workspace {noun} catalog and enable it first."
    )


def blocked_mcp_resource_result(decision: McpResourceDecision) -> dict[str, Any]:
    """Uniform, secret-free, state-indistinguishable denial payload."""
    return {
        "error": _denial_message(decision),
        "mcp_server": decision.server_name,
        "mcp_governed_kind": decision.kind,
        "blocked_by": MCP_RESOURCE_POLICY_NAME,
        "reason": decision.public_reason,
    }
