"""Workspace execution-view helpers for bounded routing and delegated runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import Project, WorkspaceCapabilityBinding, WorkspacePolicy
from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY
from .service import (
    seed_workspace_bundle_foundation,
    sync_workspace_runtime_catalog_bindings,
)


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


def _serialize_execution_binding(binding: WorkspaceCapabilityBinding) -> dict[str, Any]:
    capability_type = binding.capability_type
    contract = _normalize_mapping(capability_type.contract if capability_type is not None else {})
    return {
        "binding_key": str(binding.binding_key or "").strip(),
        "capability_kind": str(binding.capability_kind or "").strip(),
        "display_name": str(binding.display_name or "").strip(),
        "source_entity_type": str(binding.source_entity_type or "").strip(),
        "source_entity_id": str(binding.source_entity_id or "").strip(),
        "binding_status": str(binding.binding_status or "").strip() or "active",
        "is_enabled": bool(binding.is_enabled),
        "is_default": bool(binding.is_default),
        "intent_scopes": _normalize_string_list(binding.intent_scopes),
        "binding_config": _normalize_mapping(binding.binding_config),
        "policy_config": _normalize_mapping(binding.policy_config),
        "capability_type_key": str(capability_type.key or "").strip() if capability_type is not None else "",
        "capability_name": str(capability_type.name or "").strip() if capability_type is not None else "",
        "capability_description": str(capability_type.description or "").strip() if capability_type is not None else "",
        "capability_contract": contract,
        "agent_type": str(contract.get("agentType") or "").strip(),
        "runtime_target_id": (
            str(binding.binding_config.get("runtimeTargetId") or "").strip()
            or str(contract.get("runtimeTargetId") or "").strip()
        ),
    }


def normalize_workspace_execution_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    workspace_id = str(value.get("workspace_id") or value.get("workspaceId") or "").strip()
    if not workspace_id:
        return None
    bindings_by_kind_raw = value.get("bindings_by_kind") or value.get("bindingsByKind")
    bindings_by_kind = {
        str(kind).strip(): [dict(item) for item in items if isinstance(item, dict)]
        for kind, items in _normalize_mapping(bindings_by_kind_raw).items()
        if str(kind).strip() and isinstance(items, list)
    }
    return {
        "workspace_id": workspace_id,
        "default_binding_keys": {
            str(kind).strip(): str(binding_key).strip()
            for kind, binding_key in _normalize_mapping(value.get("default_binding_keys")).items()
            if str(kind).strip() and str(binding_key).strip()
        },
        "bindings_by_kind": bindings_by_kind,
        "routing_policy": _normalize_mapping(value.get("routing_policy")),
        "delegation_policy": _normalize_mapping(value.get("delegation_policy")),
        "runtime_policy": _normalize_mapping(value.get("runtime_policy")),
        "selected_binding_keys": [
            str(item).strip() for item in (value.get("selected_binding_keys") or []) if str(item).strip()
        ],
    }


async def _written_once(db: AsyncSession, write: Callable[[], Awaitable[Any]]) -> Any:
    try:
        async with db.begin_nested():
            result = await write()
            await db.flush()
            return result
    except IntegrityError:
        return None


async def _load_workspace_with_composition(
    db: AsyncSession,
    *,
    workspace_id: str,
    ensure_foundation: bool = True,
    retry: bool = True,
) -> Project | None:
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return None
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
            .where(Project.id == normalized_workspace_id)
        )
    ).scalar_one_or_none()
    if workspace is None:
        return None
    if ensure_foundation and workspace.workspace_policy is None:
        await _written_once(db, lambda: seed_workspace_bundle_foundation(db, workspace_id=normalized_workspace_id))
        return await _load_workspace_with_composition(
            db,
            workspace_id=normalized_workspace_id,
            ensure_foundation=False,
        )
    created_runtime_bindings = await _written_once(
        db, lambda: sync_workspace_runtime_catalog_bindings(db, workspace_id=normalized_workspace_id))
    if created_runtime_bindings or (created_runtime_bindings is None and retry):
        return await _load_workspace_with_composition(
            db,
            workspace_id=normalized_workspace_id,
            ensure_foundation=False,
            retry=created_runtime_bindings is not None,
        )
    return workspace


async def get_workspace_execution_view(
    db: AsyncSession,
    *,
    workspace_id: str,
    ensure_foundation: bool = True,
) -> dict[str, Any] | None:
    workspace = await _load_workspace_with_composition(
        db,
        workspace_id=workspace_id,
        ensure_foundation=ensure_foundation,
    )
    if workspace is None:
        return None
    policy: WorkspacePolicy | None = workspace.workspace_policy
    default_binding_keys = {
        str(kind).strip(): str(binding_key).strip()
        for kind, binding_key in _normalize_mapping(policy.default_bindings if policy is not None else {}).items()
        if str(kind).strip() and str(binding_key).strip()
    }
    bindings_by_kind: dict[str, list[dict[str, Any]]] = {}
    for binding in sorted(
        list(workspace.workspace_capability_bindings or []),
        key=lambda item: (str(item.capability_kind or ""), str(item.display_name or ""), str(item.binding_key or "")),
    ):
        if not binding.is_enabled or str(binding.binding_status or "").strip().lower() == "hidden":
            continue
        serialized = _serialize_execution_binding(binding)
        bindings_by_kind.setdefault(serialized["capability_kind"], []).append(serialized)
        if binding.is_default and serialized["capability_kind"] not in default_binding_keys:
            default_binding_keys[serialized["capability_kind"]] = serialized["binding_key"]
    return {
        "workspace_id": workspace.id,
        "default_binding_keys": default_binding_keys,
        "bindings_by_kind": bindings_by_kind,
        "routing_policy": _normalize_mapping(policy.routing_policy if policy is not None else {}),
        "delegation_policy": _normalize_mapping(policy.delegation_policy if policy is not None else {}),
        "runtime_policy": _normalize_mapping(policy.runtime_policy if policy is not None else {}),
        "selected_binding_keys": [],
    }


def get_workspace_default_runtime_target_id(workspace_execution_view: dict[str, Any] | None) -> str:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return ""
    default_binding_keys = normalized_view.get("default_binding_keys") or {}
    runtime_bindings = list((normalized_view.get("bindings_by_kind") or {}).get("runtime") or [])
    if not runtime_bindings:
        return ""
    # Only an explicit default counts: the first binding is never a silent default; without one
    # the platform order decides.
    default_binding_key = str(default_binding_keys.get("runtime") or "").strip()
    if default_binding_key:
        for binding in runtime_bindings:
            if str(binding.get("binding_key") or "").strip() == default_binding_key:
                return str(binding.get("source_entity_id") or "").strip()
    return ""


def derive_workspace_default_chat_selection(workspace_execution_view: dict[str, Any] | None) -> dict[str, str]:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return {
            "selected_agent_id": "",
            "selected_agent_name": "",
            "selected_agent_type": DEFAULT_AGENT_MODE_KEY,
            "selected_runtime_target_id": "",
            "selection_source": "",
        }
    bindings_by_kind = normalized_view.get("bindings_by_kind") or {}
    default_binding_keys = normalized_view.get("default_binding_keys") or {}
    agent_bindings = list(bindings_by_kind.get("agent") or [])
    runtime_target_id = get_workspace_default_runtime_target_id(normalized_view)
    default_agent_key = str(default_binding_keys.get("agent") or "").strip()
    if default_agent_key:
        for binding in agent_bindings:
            if str(binding.get("binding_key") or "").strip() != default_agent_key:
                continue
            return {
                "selected_agent_id": str(binding.get("source_entity_id") or "").strip(),
                "selected_agent_name": str(binding.get("display_name") or "").strip(),
                "selected_agent_type": str(binding.get("agent_type") or DEFAULT_AGENT_MODE_KEY).strip()
                or DEFAULT_AGENT_MODE_KEY,
                "selected_runtime_target_id": runtime_target_id,
                "selection_source": "workspace_default_agent",
            }

    return {
        "selected_agent_id": "",
        "selected_agent_name": "",
        "selected_agent_type": DEFAULT_AGENT_MODE_KEY,
        "selected_runtime_target_id": runtime_target_id,
        "selection_source": "",
    }


def build_sub_agent_workspace_execution_view(
    workspace_execution_view: dict[str, Any] | None,
    *,
    child_agent_type: str,
    inherited_agent_definition: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return None
    bindings_by_kind = normalized_view.get("bindings_by_kind") or {}
    inherited_agent_id = str((inherited_agent_definition or {}).get("id") or "").strip()
    normalized_child_type = str(child_agent_type or "").strip()

    runtime_bindings = list(bindings_by_kind.get("runtime") or [])
    runtime_default_key = str((normalized_view.get("default_binding_keys") or {}).get("runtime") or "").strip()
    if runtime_default_key:
        runtime_bindings = [
            binding
            for binding in runtime_bindings
            if str(binding.get("binding_key") or "").strip() == runtime_default_key
        ] or runtime_bindings[:1]
    elif runtime_bindings:
        runtime_bindings = runtime_bindings[:1]

    selected_binding_keys = [str(binding.get("binding_key") or "").strip() for binding in runtime_bindings]
    agent_bindings = []
    for binding in list(bindings_by_kind.get("agent") or []):
        source_entity_id = str(binding.get("source_entity_id") or "").strip()
        binding_agent_type = str(binding.get("agent_type") or "").strip()
        if inherited_agent_id and source_entity_id == inherited_agent_id:
            agent_bindings.append(binding)
            selected_binding_keys.append(str(binding.get("binding_key") or "").strip())
            continue
        if normalized_child_type and binding_agent_type == normalized_child_type:
            agent_bindings.append(binding)
            selected_binding_keys.append(str(binding.get("binding_key") or "").strip())

    return {
        "workspace_id": normalized_view["workspace_id"],
        "default_binding_keys": {
            "runtime": runtime_default_key,
        }
        if runtime_default_key
        else {},
        "bindings_by_kind": {
            "runtime": runtime_bindings,
            "agent": agent_bindings,
        },
        "routing_policy": {},
        "delegation_policy": _normalize_mapping(normalized_view.get("delegation_policy")),
        "runtime_policy": _normalize_mapping(normalized_view.get("runtime_policy")),
        "selected_binding_keys": [item for item in selected_binding_keys if item],
    }


__all__ = [
    "build_sub_agent_workspace_execution_view",
    "derive_workspace_default_chat_selection",
    "get_workspace_default_runtime_target_id",
    "get_workspace_execution_view",
    "normalize_workspace_execution_view",
]
