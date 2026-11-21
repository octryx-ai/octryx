"""Closed state vocabulary of the governed MCP resource and prompt gates.

Pure constants, shared by ``mcp_resource_identity``, ``mcp_resource_policy``, ``mcp_resource_gate``
and the discovery and audit owners, so every decision names its outcome from the same closed set.
"""

from __future__ import annotations

# Closed internal state vocabulary. Audit records carry one of these; the model
# only ever sees the uniform public reason built from it.
STATE_ALLOWED = "allowed_enabled"
STATE_NOT_MIRRORED = "not_mirrored"
STATE_DISABLED = "binding_disabled"
STATE_HIDDEN = "binding_hidden"
STATE_RETIRED = "capability_type_retired"
STATE_CONTRACT_DRIFT = "contract_drift_needs_review"
STATE_OUT_OF_SCOPE = "out_of_scope"
STATE_CREDENTIAL_URI = "credential_bearing_uri"
STATE_CREDENTIAL_METADATA = "credential_bearing_metadata"
STATE_UPSTREAM_MISSING = "upstream_item_missing"
STATE_MISSING_IDENTITY = "missing_identity"
# The catalog is keyed by the canonical (casefolded) server identity, while the
# transport is keyed by the exact configured server name. These two states cover
# the gap: no configured server owns this canonical identity, or several do and
# the platform cannot tell which one the governed catalog describes.
STATE_UNKNOWN_SERVER = "unknown_server_identity"
STATE_AMBIGUOUS_SERVER = "ambiguous_server_identity"
STATE_MISSING_WORKSPACE = "missing_workspace_context"
STATE_AMBIGUOUS_WORKSPACE = "ambiguous_workspace_context"
STATE_MISSING_DATABASE = "missing_database_context"
STATE_MISSING_USER = "missing_user_context"
MCP_RESOURCE_DECISION_STATES = (
    STATE_ALLOWED,
    STATE_NOT_MIRRORED,
    STATE_DISABLED,
    STATE_HIDDEN,
    STATE_RETIRED,
    STATE_CONTRACT_DRIFT,
    STATE_CREDENTIAL_URI,
    STATE_CREDENTIAL_METADATA,
    STATE_UPSTREAM_MISSING,
    STATE_OUT_OF_SCOPE,
    STATE_MISSING_IDENTITY,
    STATE_UNKNOWN_SERVER,
    STATE_AMBIGUOUS_SERVER,
    STATE_MISSING_WORKSPACE,
    STATE_AMBIGUOUS_WORKSPACE,
    STATE_MISSING_DATABASE,
    STATE_MISSING_USER,
)
UNVERIFIABLE_STATES = frozenset(
    {STATE_MISSING_WORKSPACE, STATE_AMBIGUOUS_WORKSPACE, STATE_MISSING_DATABASE, STATE_MISSING_USER}
)

# Discovery answers, also closed.
DISCOVERY_STATE_ENFORCED = "enforced"
DISCOVERY_STATE_NONE_VISIBLE = "no_visible_entries"
DISCOVERY_STATE_NOT_MIRRORED = "server_not_mirrored"

__all__ = [
    "DISCOVERY_STATE_ENFORCED",
    "DISCOVERY_STATE_NONE_VISIBLE",
    "DISCOVERY_STATE_NOT_MIRRORED",
    "MCP_RESOURCE_DECISION_STATES",
    "STATE_ALLOWED",
    "STATE_AMBIGUOUS_SERVER",
    "STATE_AMBIGUOUS_WORKSPACE",
    "STATE_CONTRACT_DRIFT",
    "STATE_CREDENTIAL_METADATA",
    "STATE_CREDENTIAL_URI",
    "STATE_DISABLED",
    "STATE_HIDDEN",
    "STATE_MISSING_DATABASE",
    "STATE_MISSING_IDENTITY",
    "STATE_MISSING_USER",
    "STATE_MISSING_WORKSPACE",
    "STATE_NOT_MIRRORED",
    "STATE_OUT_OF_SCOPE",
    "STATE_RETIRED",
    "STATE_UNKNOWN_SERVER",
    "STATE_UPSTREAM_MISSING",
    "UNVERIFIABLE_STATES",
]
