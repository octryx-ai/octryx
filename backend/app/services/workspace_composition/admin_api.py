"""Admin-facing read and mutation helpers for workspace composition."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import Project, WorkspaceCapabilityBinding, WorkspacePolicy
from ..mcp_capability_admin_policy import guard_mcp_capability_binding_update
from ..mcp_capability_policy import MCP_CAPABILITY_KIND
from ..mcp_resource_admin_policy import guard_mcp_resource_binding_update
from ..mcp_resource_identity import MCP_RESOURCE_BINDING_KINDS
from .service import seed_workspace_bundle_foundation, sync_workspace_runtime_catalog_bindings

_ALLOWED_BINDING_STATUSES = {"active", "hidden"}
_ALLOWED_ASSIGNMENT_MODES = {"all_installed", "selected_only"}


def _normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _serialize_binding(binding: WorkspaceCapabilityBinding) -> dict[str, Any]:
    capability_type = binding.capability_type
    return {
        "id": binding.id,
        "workspace_id": binding.workspace_id,
        "capability_type_id": binding.capability_type_id,
        "capability_kind": binding.capability_kind,
        "binding_key": binding.binding_key,
        "display_name": binding.display_name,
        "binding_status": binding.binding_status,
        "is_enabled": bool(binding.is_enabled),
        "is_default": bool(binding.is_default),
        "intent_scopes": list(binding.intent_scopes or []),
        "binding_config": _normalize_mapping(binding.binding_config),
        "policy_config": _normalize_mapping(binding.policy_config),
        "source_entity_type": binding.source_entity_type,
        "source_entity_id": binding.source_entity_id,
        "capability_type": {
            "id": capability_type.id,
            "kind": capability_type.kind,
            "key": capability_type.key,
            "name": capability_type.name,
            "description": capability_type.description or "",
            "lifecycle_status": capability_type.lifecycle_status,
            "contract": _normalize_mapping(capability_type.contract),
            "is_active": bool(capability_type.is_active),
        }
        if capability_type is not None
        else None,
    }


def _serialize_policy(policy: WorkspacePolicy | None) -> dict[str, Any]:
    if policy is None:
        return {
            "default_bindings": {},
            "routing_policy": {},
            "delegation_policy": {},
            "runtime_policy": {},
        }
    return {
        "default_bindings": _normalize_mapping(policy.default_bindings),
        "routing_policy": _normalize_mapping(policy.routing_policy),
        "delegation_policy": _normalize_mapping(policy.delegation_policy),
        "runtime_policy": _normalize_mapping(policy.runtime_policy),
    }


def _build_diagnostics(
    *,
    bindings: list[WorkspaceCapabilityBinding],
    policy: WorkspacePolicy | None,
) -> dict[str, Any]:
    policy_payload = _serialize_policy(policy)
    warnings: list[dict[str, Any]] = []

    enabled_runtime_bindings = [
        binding
        for binding in bindings
        if binding.capability_kind == "runtime" and binding.is_enabled and binding.binding_status != "hidden"
    ]
    if not enabled_runtime_bindings:
        warnings.append(
            {
                "code": "missing-runtime-binding",
                "severity": "error",
                "message": "Workspace has no enabled runtime binding.",
            }
        )

    default_bindings = _normalize_mapping(policy_payload.get("default_bindings"))
    if enabled_runtime_bindings and "runtime" not in default_bindings:
        warnings.append(
            {
                "code": "missing-default-runtime",
                "severity": "warning",
                "message": "Workspace has enabled runtime bindings but no default runtime binding.",
            }
        )

    return {"warnings": warnings}


def _build_summary(bindings: list[WorkspaceCapabilityBinding], policy: WorkspacePolicy | None) -> dict[str, Any]:
    counts_by_kind: dict[str, int] = {}
    enabled_counts_by_kind: dict[str, int] = {}
    default_binding_keys: dict[str, str] = {}
    for binding in bindings:
        counts_by_kind[binding.capability_kind] = counts_by_kind.get(binding.capability_kind, 0) + 1
        if binding.is_enabled:
            enabled_counts_by_kind[binding.capability_kind] = enabled_counts_by_kind.get(binding.capability_kind, 0) + 1
        if binding.is_default:
            default_binding_keys[binding.capability_kind] = binding.binding_key
    if policy is not None:
        default_binding_keys.update(
            {
                str(kind): str(binding_key)
                for kind, binding_key in _normalize_mapping(policy.default_bindings).items()
                if str(kind).strip() and str(binding_key).strip()
            }
        )
    return {
        "binding_counts": counts_by_kind,
        "enabled_binding_counts": enabled_counts_by_kind,
        "default_binding_keys": default_binding_keys,
    }


def _build_assignment_controls(
    bindings: list[WorkspaceCapabilityBinding],
    policy: WorkspacePolicy | None,
) -> dict[str, Any]:
    policy_payload = _serialize_policy(policy)
    routing_policy = _normalize_mapping(policy_payload.get("routing_policy"))
    runtime_policy = _normalize_mapping(policy_payload.get("runtime_policy"))
    default_bindings = _normalize_mapping(policy_payload.get("default_bindings"))
    available_agent_keys = [
        binding.binding_key for binding in bindings if binding.capability_kind == "agent"
    ]
    available_runtime_keys = [
        binding.binding_key for binding in bindings if binding.capability_kind == "runtime"
    ]
    return {
        "agent_assignment_mode": str(
            routing_policy.get("agent_assignment_mode") or "all_installed"
        ),
        "runtime_assignment_mode": str(
            runtime_policy.get("runtime_assignment_mode") or "all_installed"
        ),
        "default_agent_binding_key": str(default_bindings.get("agent") or ""),
        "default_runtime_binding_key": str(default_bindings.get("runtime") or ""),
        "available_agent_binding_keys": available_agent_keys,
        "available_runtime_binding_keys": available_runtime_keys,
    }


async def _load_workspace(
    db: AsyncSession,
    *,
    workspace_id: str,
    ensure_foundation: bool = True,
) -> Project:
    workspace = (
        await db.execute(
            select(Project)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Project.workspace_capability_bindings).selectinload(
                    WorkspaceCapabilityBinding.capability_type
                ),
                selectinload(Project.workspace_policy),
            )
            .where(Project.id == workspace_id)
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ensure_foundation and workspace.workspace_policy is None:
        await seed_workspace_bundle_foundation(db, workspace_id=workspace_id)
        await db.commit()
        return await _load_workspace(db, workspace_id=workspace_id, ensure_foundation=False)
    created_runtime_bindings = await sync_workspace_runtime_catalog_bindings(db, workspace_id=workspace_id)
    if created_runtime_bindings:
        await db.commit()
        return await _load_workspace(db, workspace_id=workspace_id, ensure_foundation=False)
    return workspace


async def get_workspace_composition_payload(db: AsyncSession, *, workspace_id: str) -> dict[str, Any]:
    workspace = await _load_workspace(db, workspace_id=workspace_id)
    bindings = sorted(
        list(workspace.workspace_capability_bindings or []),
        key=lambda item: (item.capability_kind, item.display_name.lower(), item.binding_key),
    )
    policy = workspace.workspace_policy
    diagnostics = _build_diagnostics(bindings=bindings, policy=policy)
    return {
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "description": workspace.description or "",
            "is_active": bool(workspace.is_active),
        },
        "bindings": [_serialize_binding(binding) for binding in bindings],
        "policy": _serialize_policy(policy),
        "assignment_controls": _build_assignment_controls(bindings, policy),
        "summary": _build_summary(bindings, policy),
        "diagnostics": diagnostics,
    }


async def get_workspace_composition_diagnostics(db: AsyncSession, *, workspace_id: str) -> dict[str, Any]:
    payload = await get_workspace_composition_payload(db, workspace_id=workspace_id)
    return {
        "workspace": payload["workspace"],
        "summary": payload["summary"],
        "diagnostics": payload["diagnostics"],
    }


async def update_workspace_binding(
    db: AsyncSession,
    *,
    workspace_id: str,
    binding_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workspace = await _load_workspace(db, workspace_id=workspace_id)
    binding = next((item for item in workspace.workspace_capability_bindings if item.id == binding_id), None)
    if binding is None:
        raise HTTPException(status_code=404, detail="Workspace binding not found")
    if binding.capability_kind == MCP_CAPABILITY_KIND:
        # Mirrored capability identity is server-owned; only governance fields
        # pass (see ``services/mcp_capability_admin_policy``).
        payload = guard_mcp_capability_binding_update(binding, payload)
    elif binding.capability_kind in MCP_RESOURCE_BINDING_KINDS:
        # Same rule for mirrored MCP resources and prompts
        # (see ``services/mcp_resource_admin_policy``).
        payload = guard_mcp_resource_binding_update(binding, payload)

    normalized_status = None
    if "binding_status" in payload and payload.get("binding_status") is not None:
        normalized_status = str(payload.get("binding_status") or "").strip().lower()
        if normalized_status not in _ALLOWED_BINDING_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported workspace binding status")
        binding.binding_status = normalized_status
        if normalized_status == "hidden":
            binding.is_enabled = False
            binding.is_default = False

    if "display_name" in payload and payload.get("display_name") is not None:
        binding.display_name = str(payload.get("display_name") or "").strip() or binding.binding_key
    if "intent_scopes" in payload and payload.get("intent_scopes") is not None:
        binding.intent_scopes = _normalize_string_list(payload.get("intent_scopes"))
    if "binding_config" in payload and payload.get("binding_config") is not None:
        binding.binding_config = _normalize_mapping(payload.get("binding_config"))
    if "policy_config" in payload and payload.get("policy_config") is not None:
        binding.policy_config = _normalize_mapping(payload.get("policy_config"))
    if "is_enabled" in payload and payload.get("is_enabled") is not None:
        binding.is_enabled = bool(payload.get("is_enabled"))
        if not binding.is_enabled:
            binding.is_default = False

    workspace_policy = workspace.workspace_policy
    if workspace_policy is None:
        raise HTTPException(status_code=500, detail="Workspace policy missing after foundation seed")

    if "is_default" in payload and payload.get("is_default") is not None:
        requested_default = bool(payload.get("is_default"))
        if requested_default and (not binding.is_enabled or binding.binding_status == "hidden"):
            raise HTTPException(status_code=400, detail="Default workspace binding must stay enabled and visible")
        if requested_default:
            for sibling in workspace.workspace_capability_bindings:
                if sibling.capability_kind == binding.capability_kind:
                    sibling.is_default = sibling.id == binding.id
        else:
            binding.is_default = False

    default_bindings = _normalize_mapping(workspace_policy.default_bindings)
    if binding.is_default:
        default_bindings[binding.capability_kind] = binding.binding_key
    elif default_bindings.get(binding.capability_kind) == binding.binding_key:
        default_bindings.pop(binding.capability_kind, None)
    workspace_policy.default_bindings = default_bindings

    await db.commit()
    return await get_workspace_composition_payload(db, workspace_id=workspace_id)


async def update_workspace_policy(
    db: AsyncSession,
    *,
    workspace_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workspace = await _load_workspace(db, workspace_id=workspace_id)
    workspace_policy = workspace.workspace_policy
    if workspace_policy is None:
        raise HTTPException(status_code=500, detail="Workspace policy missing after foundation seed")

    if "default_bindings" in payload and payload.get("default_bindings") is not None:
        requested_defaults: dict[str, str] = {}
        bindings_by_key = {binding.binding_key: binding for binding in workspace.workspace_capability_bindings}
        for kind, binding_key in _normalize_mapping(payload.get("default_bindings")).items():
            normalized_kind = str(kind or "").strip()
            normalized_key = str(binding_key or "").strip()
            if not normalized_kind or not normalized_key:
                raise HTTPException(status_code=400, detail="Workspace default bindings require non-empty keys")
            binding = bindings_by_key.get(normalized_key)
            if binding is None or binding.capability_kind != normalized_kind:
                raise HTTPException(status_code=400, detail="Workspace default binding references an unknown binding")
            if not binding.is_enabled or binding.binding_status == "hidden":
                raise HTTPException(
                    status_code=400,
                    detail="Workspace default bindings must reference enabled bindings",
                )
            requested_defaults[normalized_kind] = normalized_key

        for binding in workspace.workspace_capability_bindings:
            binding.is_default = requested_defaults.get(binding.capability_kind) == binding.binding_key
        workspace_policy.default_bindings = requested_defaults

    for field_name in (
        "routing_policy",
        "delegation_policy",
        "runtime_policy",
    ):
        if field_name in payload and payload.get(field_name) is not None:
            setattr(workspace_policy, field_name, _normalize_mapping(payload.get(field_name)))

    await db.commit()
    return await get_workspace_composition_payload(db, workspace_id=workspace_id)


def _normalize_assignment_mode(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_ASSIGNMENT_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported {field_name}")
    return normalized


def _validate_assignment_binding_key(
    *,
    bindings_by_key: dict[str, WorkspaceCapabilityBinding],
    binding_key: str,
    capability_kind: str,
    allow_empty: bool = True,
) -> str:
    normalized_key = str(binding_key or "").strip()
    if not normalized_key and allow_empty:
        return ""
    binding = bindings_by_key.get(normalized_key)
    if binding is None or binding.capability_kind != capability_kind:
        raise HTTPException(status_code=400, detail="Assignment references an unknown binding")
    if not binding.is_enabled or binding.binding_status == "hidden":
        raise HTTPException(status_code=400, detail="Assignment bindings must reference enabled bindings")
    return normalized_key


async def update_workspace_assignment_controls(
    db: AsyncSession,
    *,
    workspace_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workspace = await _load_workspace(db, workspace_id=workspace_id)
    workspace_policy = workspace.workspace_policy
    if workspace_policy is None:
        raise HTTPException(status_code=500, detail="Workspace policy missing after foundation seed")

    bindings_by_key = {binding.binding_key: binding for binding in workspace.workspace_capability_bindings}
    default_bindings = _normalize_mapping(workspace_policy.default_bindings)
    routing_policy = _normalize_mapping(workspace_policy.routing_policy)
    runtime_policy = _normalize_mapping(workspace_policy.runtime_policy)

    if "agent_assignment_mode" in payload and payload.get("agent_assignment_mode") is not None:
        routing_policy["agent_assignment_mode"] = _normalize_assignment_mode(
            payload.get("agent_assignment_mode"),
            field_name="agent assignment mode",
        )
    if "runtime_assignment_mode" in payload and payload.get("runtime_assignment_mode") is not None:
        runtime_policy["runtime_assignment_mode"] = _normalize_assignment_mode(
            payload.get("runtime_assignment_mode"),
            field_name="runtime assignment mode",
        )

    if "default_agent_binding_key" in payload and payload.get("default_agent_binding_key") is not None:
        normalized_key = _validate_assignment_binding_key(
            bindings_by_key=bindings_by_key,
            binding_key=payload.get("default_agent_binding_key"),
            capability_kind="agent",
        )
        if normalized_key:
            default_bindings["agent"] = normalized_key
        else:
            default_bindings.pop("agent", None)

    if "default_runtime_binding_key" in payload and payload.get("default_runtime_binding_key") is not None:
        normalized_key = _validate_assignment_binding_key(
            bindings_by_key=bindings_by_key,
            binding_key=payload.get("default_runtime_binding_key"),
            capability_kind="runtime",
        )
        if normalized_key:
            default_bindings["runtime"] = normalized_key
        else:
            default_bindings.pop("runtime", None)

    # A Workspace has no "fallback runtime"; failover is the platform's, bounded by the
    # Workspace's models. A stored value is dropped on the next save.
    runtime_policy.pop("fallback_runtime_binding_key", None)


    for binding in workspace.workspace_capability_bindings:
        binding.is_default = default_bindings.get(binding.capability_kind) == binding.binding_key

    workspace_policy.default_bindings = default_bindings
    workspace_policy.routing_policy = routing_policy
    workspace_policy.runtime_policy = runtime_policy

    await db.commit()
    return await get_workspace_composition_payload(db, workspace_id=workspace_id)


# The loaded Workspace with its bindings and policy (foundation seeded, runtime bindings synced) for other owners
# of Workspace composition data (``workspace_models``).
load_workspace_composition = _load_workspace


__all__ = [
    "load_workspace_composition",
    "get_workspace_composition_diagnostics",
    "get_workspace_composition_payload",
    "update_workspace_assignment_controls",
    "update_workspace_binding",
    "update_workspace_policy",
]
