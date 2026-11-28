"""Admin service for runtime settings and targets; the settings and targets submodules implement them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ControlPlaneRuntimeTarget
from . import _admin_runtime_settings as _settings
from . import _admin_runtime_targets as _targets
from ._admin_runtime_audit import _record_runtime_audit, _runtime_target_audit_snapshot


async def get_runtime_settings(
    db: AsyncSession,
    *,
    get_or_create_control_plane_config_func: Callable[..., Any],
    project_id: str | None = None,
) -> dict[str, Any]:
    return await _settings.get_runtime_settings(
        db,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config_func,
        project_id=project_id,
    )


async def update_runtime_settings(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    get_or_create_control_plane_config_func: Callable[..., Any],
    project_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    before = await get_runtime_settings(
        db,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config_func,
        project_id=project_id,
    )
    result = await _settings.update_runtime_settings(
        db,
        payload=payload,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config_func,
        project_id=project_id,
    )
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.settings.updated",
        resource_type="runtime_settings",
        resource_id=normalized_project_id or "global",
        project_id=normalized_project_id or None,
        before=before,
        after=result,
        details={
            "operation": "update_runtime_settings",
            "payload_keys": sorted(str(key) for key in payload),
            "project_id": normalized_project_id or None,
        },
    )
    await db.commit()
    return result


async def list_runtimes(
    db: AsyncSession,
    *,
    get_runtime_targets_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    return await _targets.list_runtimes(
        db,
        get_runtime_targets_func=get_runtime_targets_func,
        serialize_runtime_target=serialize_runtime_target,
    )


async def add_runtime(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    upsert_runtime_target_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    result = await _targets.add_runtime(
        db,
        payload=payload,
        upsert_runtime_target_func=upsert_runtime_target_func,
        serialize_runtime_target=serialize_runtime_target,
    )
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.created",
        resource_type="runtime_target",
        resource_id=str(result.get("id") or ""),
        project_id=None,
        before=None,
        after=result,
        details={
            "operation": "add_runtime",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return result


async def move_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    direction: str,
    move_runtime_target_func: Callable[..., Any],
    get_runtime_targets_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
    actor_user_id: str | None = None,
) -> list[dict[str, Any]]:
    before = await list_runtimes(
        db,
        get_runtime_targets_func=get_runtime_targets_func,
        serialize_runtime_target=serialize_runtime_target,
    )
    result = await _targets.move_runtime(
        db,
        target_id=target_id,
        direction=direction,
        move_runtime_target_func=move_runtime_target_func,
        get_runtime_targets_func=get_runtime_targets_func,
        serialize_runtime_target=serialize_runtime_target,
    )
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.moved",
        resource_type="runtime_targets",
        resource_id=target_id,
        project_id=None,
        before=before,
        after=result,
        details={
            "operation": "move_runtime",
            "direction": direction,
        },
    )
    await db.commit()
    return result


async def toggle_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    toggle_runtime_target_func: Callable[..., Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    result = await _targets.toggle_runtime(
        db,
        target_id=target_id,
        toggle_runtime_target_func=toggle_runtime_target_func,
        serialize_runtime_target=serialize_runtime_target,
    )
    after = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.toggled",
        resource_type="runtime_target",
        resource_id=target_id,
        project_id=None,
        before=before,
        after=after,
        details={"operation": "toggle_runtime"},
    )
    await db.commit()
    return result


async def update_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    payload: dict[str, Any],
    serialize_runtime_target: Callable[..., dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    result = await _targets.update_runtime(
        db,
        target_id=target_id,
        payload=payload,
        serialize_runtime_target=serialize_runtime_target,
    )
    after = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.updated",
        resource_type="runtime_target",
        resource_id=target_id,
        project_id=None,
        before=before,
        after=after,
        details={
            "operation": "update_runtime",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return result


async def delete_runtime(
    db: AsyncSession,
    *,
    target_id: str,
    delete_runtime_target_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before = _runtime_target_audit_snapshot(await db.get(ControlPlaneRuntimeTarget, target_id))
    result = await _targets.delete_runtime(
        db,
        target_id=target_id,
        delete_runtime_target_func=delete_runtime_target_func,
    )
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.target.deleted",
        resource_type="runtime_target",
        resource_id=target_id,
        project_id=None,
        before=before,
        after=None,
        details={"operation": "delete_runtime"},
    )
    await db.commit()
    return result


__all__ = [
    "get_runtime_settings",
    "update_runtime_settings",
    "list_runtimes",
    "add_runtime",
    "move_runtime",
    "toggle_runtime",
    "update_runtime",
    "delete_runtime",
]
