"""Audited reads and writes of context budget profiles."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import _admin_runtime_targets as _targets
from ._admin_runtime_audit import _find_catalog_item, _record_runtime_audit


async def get_context_budget_profiles(db: AsyncSession) -> list[dict[str, Any]]:
    return await _targets.get_context_budget_profiles(db)


async def save_context_budget_profile(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    before_catalog = await _targets.get_context_budget_profiles(db)
    result = await _targets.save_context_budget_profile(db, payload=payload)
    resource_id = str(result.get("id") or payload.get("id") or "")
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.context_budget_profile.saved",
        resource_type="context_budget_profile",
        resource_id=resource_id,
        before=_find_catalog_item(before_catalog, resource_id),
        after=result,
        details={
            "operation": "save_context_budget_profile",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return result


async def remove_context_budget_profile(
    db: AsyncSession,
    *,
    profile_id: str,
    actor_user_id: str | None = None,
) -> list[dict[str, Any]]:
    before_catalog = await _targets.get_context_budget_profiles(db)
    before = _find_catalog_item(before_catalog, profile_id)
    result = await _targets.remove_context_budget_profile(db, profile_id=profile_id)
    _record_runtime_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.runtime.context_budget_profile.deleted",
        resource_type="context_budget_profile",
        resource_id=profile_id,
        before=before,
        after=None,
        details={"operation": "remove_context_budget_profile"},
    )
    await db.commit()
    return result
