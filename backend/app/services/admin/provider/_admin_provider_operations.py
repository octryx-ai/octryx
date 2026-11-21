"""Catalog of provider and model admin operations with their guard and audit contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderAdminOperation:
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


PROVIDER_ADMIN_OPERATION_CATALOG: tuple[ProviderAdminOperation, ...] = (
    ProviderAdminOperation(
        name="list_providers",
        category="provider",
        description="List provider settings for the admin panel.",
        auth_guard="_require_admin_api",
        policy_sensitive=False,
        audit_required=False,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/providers", "/api/v1/providers"),
    ),
    ProviderAdminOperation(
        name="create_provider",
        category="provider",
        description="Create a provider configuration and store credentials through the secret boundary when available.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/providers", "/api/v1/providers"),
    ),
    ProviderAdminOperation(
        name="update_provider",
        category="provider",
        description="Update provider metadata, runtime defaults, and credential references.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/providers/{provider_id}",),
    ),
    ProviderAdminOperation(
        name="delete_provider",
        category="provider",
        description="Delete provider configuration and dependent runtime/model rows.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/providers/{provider_id}",),
    ),
    ProviderAdminOperation(
        name="sync_provider_models",
        category="model",
        description="Sync provider model metadata through the provider client boundary.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=True,
        route_surfaces=("/chat/api/panel/providers/{provider_id}/sync", "/api/v1/providers/{provider_id}/models/sync"),
    ),
    ProviderAdminOperation(
        name="update_model",
        category="model",
        description="Update admin-managed model capabilities, pricing, and budget fields.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/providers/{provider_id}/models/{model_id}",),
    ),
    ProviderAdminOperation(
        name="add_model",
        category="model",
        description="Register an admin-managed provider model manually.",
        auth_guard="_require_admin_api",
        policy_sensitive=True,
        audit_required=True,
        secret_sensitive=False,
        route_surfaces=("/chat/api/panel/providers/{provider_id}/models",),
    ),
)


def list_provider_admin_operations() -> list[dict[str, Any]]:
    return [operation.to_payload() for operation in PROVIDER_ADMIN_OPERATION_CATALOG]


def get_provider_admin_operation(name: str) -> dict[str, Any] | None:
    normalized = str(name or "").strip()
    for operation in PROVIDER_ADMIN_OPERATION_CATALOG:
        if operation.name == normalized:
            return operation.to_payload()
    return None
