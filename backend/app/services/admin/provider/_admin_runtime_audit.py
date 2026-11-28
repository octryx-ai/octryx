"""Audit snapshots and the audit writer shared by the runtime admin operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ControlPlaneRuntimeTarget
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


def _list_audit_snapshot(payload: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(payload), "items": payload}


def _record_runtime_audit(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    project_id: str | None,
    before: dict[str, Any] | list[dict[str, Any]] | None,
    after: dict[str, Any] | list[dict[str, Any]] | None,
    details: dict[str, Any] | None = None,
) -> None:
    safe_before = _list_audit_snapshot(before) if isinstance(before, list) else before
    safe_after = _list_audit_snapshot(after) if isinstance(after, list) else after
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        before=safe_before,
        after=safe_after,
        details=details,
    )
