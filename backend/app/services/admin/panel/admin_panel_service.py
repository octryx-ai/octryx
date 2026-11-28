"""Service helpers for admin-panel approval and exec-policy flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ExecPolicyConfig
from ...exec_policy import (
    delete_exec_policy_config,
    get_effective_exec_policy_config,
    get_global_exec_policy_config,
    list_exec_policy_configs,
    upsert_exec_policy_config,
    upsert_global_exec_policy_config,
)
from ..governance.admin_config_audit_service import record_admin_config_audit


async def get_exec_policy_payload(db: AsyncSession) -> dict[str, Any]:
    return await get_effective_exec_policy_config(db)


def _exec_policy_audit_snapshot(config: ExecPolicyConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    return {
        "id": config.id,
        "name": config.name,
        "project_id": config.project_id,
        "priority": config.priority,
        "is_active": config.is_active,
        "config": config.config_json if isinstance(config.config_json, dict) else {},
    }


async def update_global_exec_policy_payload(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before = _exec_policy_audit_snapshot(await get_global_exec_policy_config(db))
    updated = await upsert_global_exec_policy_config(db, payload)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.governance.exec_policy.global_updated",
        resource_type="exec_policy_config",
        resource_id=updated.id,
        project_id=updated.project_id,
        before=before,
        after=_exec_policy_audit_snapshot(updated),
        details={
            "operation": "update_global_exec_policy_payload",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return updated.config_json or {}


async def list_exec_policy_payloads(
    db: AsyncSession,
    *,
    serialize_exec_policy_config: Callable[[ExecPolicyConfig], dict[str, Any]],
) -> list[dict[str, Any]]:
    configs = await list_exec_policy_configs(db)
    for config in configs:
        if config.project_id:
            await db.refresh(config, attribute_names=["project"])
    return [serialize_exec_policy_config(config) for config in configs]


async def create_exec_policy_payload(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    serialize_exec_policy_config: Callable[[ExecPolicyConfig], dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    config_json = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    created = await upsert_exec_policy_config(
        db,
        config_id=None,
        name=str(payload.get("name") or "Exec Policy"),
        project_id=str(payload.get("projectId") or "").strip() or None,
        priority=int(payload.get("priority") or 100),
        is_active=bool(payload.get("isActive", True)),
        config_json=config_json,
    )
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.governance.exec_policy.created",
        resource_type="exec_policy_config",
        resource_id=created.id,
        project_id=created.project_id,
        before=None,
        after=_exec_policy_audit_snapshot(created),
        details={
            "operation": "create_exec_policy_payload",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    await db.refresh(created)
    if created.project_id:
        await db.refresh(created, attribute_names=["project"])
    return serialize_exec_policy_config(created)


async def update_exec_policy_payload(
    db: AsyncSession,
    *,
    config_id: str,
    payload: dict[str, Any],
    serialize_exec_policy_config: Callable[[ExecPolicyConfig], dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    existing = await db.get(ExecPolicyConfig, config_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Exec policy not found")
    before = _exec_policy_audit_snapshot(existing)
    config_json = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    updated = await upsert_exec_policy_config(
        db,
        config_id=config_id,
        name=str(payload.get("name") or existing.name or "Exec Policy"),
        project_id=str(payload.get("projectId") or "").strip() or None,
        priority=int(payload.get("priority") or existing.priority or 100),
        is_active=bool(payload.get("isActive", existing.is_active)),
        config_json=config_json,
    )
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.governance.exec_policy.updated",
        resource_type="exec_policy_config",
        resource_id=updated.id,
        project_id=updated.project_id,
        before=before,
        after=_exec_policy_audit_snapshot(updated),
        details={
            "operation": "update_exec_policy_payload",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    await db.refresh(updated)
    if updated.project_id:
        await db.refresh(updated, attribute_names=["project"])
    return serialize_exec_policy_config(updated)


async def delete_exec_policy_payload(
    db: AsyncSession,
    *,
    config_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    existing = await db.get(ExecPolicyConfig, config_id)
    before = _exec_policy_audit_snapshot(existing)
    deleted = await delete_exec_policy_config(db, config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Exec policy not found")
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.governance.exec_policy.deleted",
        resource_type="exec_policy_config",
        resource_id=config_id,
        project_id=existing.project_id if existing else None,
        before=before,
        after=None,
        details={"operation": "delete_exec_policy_payload"},
    )
    await db.commit()
    return {"ok": True}
