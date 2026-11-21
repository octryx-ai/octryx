"""Runtime-target admin actions of the control plane, each recorded in the config audit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ControlPlaneRuntimeTarget, LLMProvider
from ..governance.admin_config_audit_service import record_admin_config_audit


def _runtime_target_audit_snapshot(target: ControlPlaneRuntimeTarget | None) -> dict[str, Any]:
    if target is None:
        return {}
    return {
        "id": target.id,
        "config_id": target.config_id,
        "provider_id": target.provider_id,
        "model_id": target.model_id,
        "priority": target.priority,
        "is_active": target.is_active,
        "use_case_tags": target.use_case_tags,
        "capability_tags": target.capability_tags,
        "accepts_temperature": target.accepts_temperature,
    }


async def save_control_plane_runtime_target(
    db: AsyncSession,
    *,
    provider_id: str,
    model_id: str,
    make_primary: bool,
    is_active: bool,
    upsert_runtime_target_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> str:
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    target = await upsert_runtime_target_func(
        db,
        provider=provider,
        model_id=model_id,
        make_primary=make_primary,
        is_active=is_active,
    )
    provider.is_active = True
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.saved",
        resource_type="runtime_target",
        resource_id=target.id,
        before=None,
        after=_runtime_target_audit_snapshot(target),
        details={
            "operation": "save_control_plane_runtime_target",
            "make_primary": make_primary,
        },
    )
    await db.commit()
    return provider.id


async def move_control_plane_runtime_target(
    db: AsyncSession,
    *,
    target_id: str,
    direction: str,
    move_runtime_target_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> None:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    await move_runtime_target_func(db, target_id, direction)
    after = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.moved",
        resource_type="runtime_target",
        resource_id=target_id,
        before=before,
        after=after,
        details={
            "operation": "move_control_plane_runtime_target",
            "direction": direction,
        },
    )
    await db.commit()


async def toggle_control_plane_runtime_target(
    db: AsyncSession,
    *,
    target_id: str,
    toggle_runtime_target_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> None:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    await toggle_runtime_target_func(db, target_id)
    after = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.toggled",
        resource_type="runtime_target",
        resource_id=target_id,
        before=before,
        after=after,
        details={"operation": "toggle_control_plane_runtime_target"},
    )
    await db.commit()


async def delete_control_plane_runtime_target(
    db: AsyncSession,
    *,
    target_id: str,
    delete_runtime_target_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> None:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    await delete_runtime_target_func(db, target_id)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.deleted",
        resource_type="runtime_target",
        resource_id=target_id,
        before=before,
        after=None,
        details={"operation": "delete_control_plane_runtime_target"},
    )
    await db.commit()
