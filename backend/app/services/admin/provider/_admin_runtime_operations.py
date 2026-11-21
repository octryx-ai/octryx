"""Catalog of runtime admin operations with their guard and audit contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeAdminOperation:
    name: str
    category: str
    description: str
    auth_guard: str
    policy_sensitive: bool
    audit_required: bool
    route_surfaces: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["route_surfaces"] = list(self.route_surfaces)
        return payload


RUNTIME_ADMIN_OPERATION_CATALOG: tuple[RuntimeAdminOperation, ...] = (
    RuntimeAdminOperation(
        name="get_runtime_settings",
        category="settings",
        description="Read global or project-scoped runtime settings for the admin panel.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        route_surfaces=("/chat/api/panel/runtime-settings",),
    ),
    RuntimeAdminOperation(
        name="update_runtime_settings",
        category="settings",
        description="Update runtime, execution, safety, token, and cost-limit settings.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/runtime-settings",),
    ),
    RuntimeAdminOperation(
        name="list_runtimes",
        category="runtime_target",
        description="List configured runtime targets in admin-visible order.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        route_surfaces=("/chat/api/panel/runtimes",),
    ),
    RuntimeAdminOperation(
        name="add_runtime",
        category="runtime_target",
        description="Create or upsert an admin-managed runtime target.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/runtimes", "/control-plane/runtime-targets/save"),
    ),
    RuntimeAdminOperation(
        name="move_runtime",
        category="runtime_target",
        description="Change runtime target priority/order.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/runtimes/{target_id}/move", "/control-plane/runtime-targets/{target_id}/move"),
    ),
    RuntimeAdminOperation(
        name="toggle_runtime",
        category="runtime_target",
        description="Enable or disable a runtime target.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=(
            "/chat/api/panel/runtimes/{target_id}/toggle",
            "/control-plane/runtime-targets/{target_id}/toggle",
        ),
    ),
    RuntimeAdminOperation(
        name="update_runtime",
        category="runtime_target",
        description="Update runtime target metadata such as active state, model id, and use-case tags.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/runtimes/{target_id}",),
    ),
    RuntimeAdminOperation(
        name="delete_runtime",
        category="runtime_target",
        description="Delete an admin-managed runtime target.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/runtimes/{target_id}", "/control-plane/runtime-targets/{target_id}/delete"),
    ),
    RuntimeAdminOperation(
        name="save_context_budget_profile",
        category="context_budget",
        description="Create or update a context budget profile.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        route_surfaces=("/chat/api/panel/context-budget-profiles",),
    ),
)


def list_runtime_admin_operations() -> list[dict[str, Any]]:
    return [operation.to_payload() for operation in RUNTIME_ADMIN_OPERATION_CATALOG]


def get_runtime_admin_operation(name: str) -> dict[str, Any] | None:
    normalized = str(name or "").strip()
    for operation in RUNTIME_ADMIN_OPERATION_CATALOG:
        if operation.name == normalized:
            return operation.to_payload()
    return None
