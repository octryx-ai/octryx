"""The resource type and the fixed ``action`` values of MCP server registry audit records."""

from __future__ import annotations

from .mcp_access_policy import DENIAL_REASONS

RESOURCE_TYPE = "mcp_server_registration"

ACTION_CREATED = "created"
ACTION_DELETED = "deleted"
ACTION_ACTIVATION_CHANGED = "activation_changed"
ACTION_CONFIGURATION_UPDATED = "configuration_updated"
ACTION_CONNECTED = "connected"
ACTION_CONNECTION_FAILED = "connection_failed"
ACTION_DISCONNECTED = "disconnected"

READINESS_SERVER_INACTIVE = "server_inactive"
READINESS_MISSING_SECRET = "missing_or_invalid_secret_reference"
BLOCK_RUNTIME_NAME_CONFLICT = "runtime_name_conflict"
BLOCK_REASONS = DENIAL_REASONS | {READINESS_SERVER_INACTIVE, READINESS_MISSING_SECRET, BLOCK_RUNTIME_NAME_CONFLICT}


def connect_blocked(reason: str) -> str:
    return f"connect_blocked:{reason}"


ALL_ACTIONS = frozenset({
    ACTION_CREATED, ACTION_DELETED, ACTION_ACTIVATION_CHANGED, ACTION_CONFIGURATION_UPDATED, ACTION_CONNECTED,
    ACTION_CONNECTION_FAILED, ACTION_DISCONNECTED, *(connect_blocked(reason) for reason in BLOCK_REASONS),
})
