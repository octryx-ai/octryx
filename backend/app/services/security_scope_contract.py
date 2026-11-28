"""Canonical security scope and permission contract for retained backend policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class PermissionDefinition:
    resource: str
    action: str
    category: str
    scope: str

    def as_catalog_item(self) -> dict[str, object]:
        return {"resource": self.resource, "action": self.action, "enforced": self.key in ENFORCED_PERMISSIONS}

    @property
    def key(self) -> tuple[str, str]:
        return (self.resource, self.action)


# The permissions a check in the platform actually asks for. Every other catalog
# permission can be granted but has no effect yet; Roles shows it as "Not enforced yet". Kept in step with the code by
# ``tests/services/security/test_permission_enforcement_markers.py``.
ENFORCED_PERMISSIONS: Final[frozenset[tuple[str, str]]] = frozenset({
    ("auth", "login"),
    ("users", "read"), ("users", "write"),
    ("roles", "read"), ("roles", "write"),
    ("api_keys", "read"), ("api_keys", "write"), ("api_keys", "self_read"), ("api_keys", "self_write"),
    ("identity_providers", "read"), ("identity_providers", "write"),
    ("projects", "read"), ("projects", "write"),
    ("audit", "read"),
})


def _permission(resource: str, action: str, category: str, scope: str) -> PermissionDefinition:
    return PermissionDefinition(resource=resource, action=action, category=category, scope=scope)


PERMISSION_DEFINITIONS: Final[tuple[PermissionDefinition, ...]] = (
    _permission("auth", "login", "auth", "auth:login"),
    _permission("users", "read", "admin", "users:read"),
    _permission("users", "write", "admin", "users:write"),
    _permission("roles", "read", "admin", "roles:read"),
    _permission("roles", "write", "admin", "roles:write"),
    _permission("api_keys", "read", "auth", "api_keys:read"),
    _permission("api_keys", "write", "auth", "api_keys:write"),
    _permission("api_keys", "self_read", "auth", "api_keys:self_read"),
    _permission("api_keys", "self_write", "auth", "api_keys:self_write"),
    _permission("identity_providers", "read", "auth", "identity_providers:read"),
    _permission("identity_providers", "write", "auth", "identity_providers:write"),
    _permission("projects", "read", "project", "projects:read"),
    _permission("projects", "write", "project", "projects:write"),
    _permission("providers", "read", "runtime", "providers:read"),
    _permission("providers", "write", "runtime", "providers:write"),
    _permission("runtimes", "read", "runtime", "runtimes:read"),
    _permission("runtimes", "write", "runtime", "runtimes:write"),
    _permission("knowledge", "read", "knowledge", "knowledge:read"),
    _permission("knowledge", "write", "knowledge", "knowledge:write"),
    _permission("tools", "read", "tool", "tools:read"),
    _permission("tools", "write", "tool", "tools:write"),
    _permission("tools", "execute", "tool", "tools:execute"),
    _permission("connectors", "read", "connector", "connectors:read"),
    _permission("connectors", "write", "connector", "connectors:write"),
    _permission("source_control", "read", "connector", "source_control:read"),
    _permission("source_control", "write", "connector", "source_control:write"),
    _permission("database_tools", "read", "tool", "database:read"),
    _permission("database_tools", "write", "tool", "database:write"),
    _permission("workflows", "read", "workflow", "workflow:read"),
    _permission("workflows", "write", "workflow", "workflow:write"),
    _permission("workflows", "execute", "workflow", "workflow:execute"),
    _permission("sessions", "read", "session", "sessions:read"),
    _permission("sessions", "write", "session", "sessions:write"),
    _permission("tasks", "read", "workflow", "tasks:read"),
    _permission("tasks", "trigger", "workflow", "tasks:trigger"),
    _permission("audit", "read", "audit", "audit:read"),
)


API_KEY_SCOPE_DEFINITIONS: Final[tuple[str, ...]] = (
    "read",
    "write",
    "admin",
    "knowledge:read",
    "knowledge:write",
    "mcp:knowledge:read",
    "engineering_packs:read",
    "session:read",
    "session:write",
    "sessions:read",
    "sessions:write",
    "tasks:read",
    "tasks:trigger",
    "project:read",
    "project:write",
    "api_keys:read",
    "api_keys:write",
    "tools:read",
    "tools:execute",
    "connectors:read",
    "connectors:write",
    "source_control:read",
    "source_control:write",
    "database:read",
    "database:write",
    "workflow:read",
    "workflow:write",
    "workflow:execute",
    "work:manage",
    # Agent gateway (octryx-claude): invoke governed models through the platform.
    "model:invoke",
)


CORE_ROLE_SCOPE_MAP: Final[dict[str, tuple[str, ...]]] = {
    "admin": ("admin", *API_KEY_SCOPE_DEFINITIONS),
    "operator": (
        "read",
        "write",
        "knowledge:read",
        "knowledge:write",
        "sessions:read",
        "sessions:write",
        "tasks:read",
        "tasks:trigger",
        "project:read",
        "project:write",
        "tools:read",
        "tools:execute",
        "connectors:read",
        "source_control:read",
        "workflow:read",
        "workflow:execute",
    ),
    "technical": (
        "read",
        "knowledge:read",
        "sessions:read",
        "tasks:read",
        "project:read",
        "tools:read",
        "tools:execute",
        "connectors:read",
        "source_control:read",
        "source_control:write",
        "database:read",
        "workflow:read",
        "workflow:execute",
    ),
    "viewer": (
        "read",
        "knowledge:read",
        "session:read",
        "sessions:read",
        "project:read",
        "tools:read",
        "workflow:read",
    ),
}


def permission_catalog() -> list[dict[str, str]]:
    return [definition.as_catalog_item() for definition in PERMISSION_DEFINITIONS]


def permission_keys() -> frozenset[tuple[str, str]]:
    return frozenset(definition.key for definition in PERMISSION_DEFINITIONS)


def allowed_api_key_scopes() -> frozenset[str]:
    return frozenset(API_KEY_SCOPE_DEFINITIONS)


def core_role_scopes(role_name: str) -> tuple[str, ...]:
    return CORE_ROLE_SCOPE_MAP.get(str(role_name or "").strip().lower(), ())


def scope_contract_summary() -> dict[str, object]:
    return {
        "permissions": [
            {
                "resource": definition.resource,
                "action": definition.action,
                "category": definition.category,
                "scope": definition.scope,
            }
            for definition in PERMISSION_DEFINITIONS
        ],
        "api_key_scopes": list(API_KEY_SCOPE_DEFINITIONS),
        "core_role_scopes": {role: list(scopes) for role, scopes in CORE_ROLE_SCOPE_MAP.items()},
    }
