"""Catalog of connector admin operations with their guard and audit contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConnectorAdminOperation:
    name: str
    category: str
    description: str
    auth_guard: str
    policy_sensitive: bool
    audit_required: bool
    secret_sensitive: bool
    route_surfaces: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["route_surfaces"] = list(self.route_surfaces)
        return payload


CONNECTOR_ADMIN_OPERATION_CATALOG: tuple[ConnectorAdminOperation, ...] = (
    ConnectorAdminOperation(
        name="list_connectors",
        category="connector_settings",
        description="List admin-visible connector settings with public config fields and secret status only.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/connectors",),
    ),
    ConnectorAdminOperation(
        name="list_tool_catalog_payload",
        category="tool_visibility",
        description="List runtime-visible tool catalog entries after connector activation gating.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/tool-catalog",),
    ),
    ConnectorAdminOperation(
        name="save_connector",
        category="connector_settings",
        description="Persist connector activation, public config, secret references, and connector tool policy.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/connectors/{tool_name}",),
    ),
    ConnectorAdminOperation(
        name="test_connector",
        category="connector_health",
        description="Resolve connector secret references server-side and run a configured connection test.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/connectors/{tool_name}/test",),
    ),
    ConnectorAdminOperation(
        name="list_connector_health_history",
        category="connector_health",
        description="Read connector health log history for admin diagnosis.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/connectors/{tool_name}/health-log",),
    ),
    ConnectorAdminOperation(
        name="delete_connector",
        category="connector_settings",
        description="Delete connector config and connector policy, making connector-owned tools unavailable.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/connectors/{tool_name}",),
    ),
)


def list_connector_admin_operations() -> list[dict[str, Any]]:
    return [operation.to_payload() for operation in CONNECTOR_ADMIN_OPERATION_CATALOG]


def get_connector_admin_operation(name: str) -> dict[str, Any] | None:
    for operation in CONNECTOR_ADMIN_OPERATION_CATALOG:
        if operation.name == name:
            return operation.to_payload()
    return None
