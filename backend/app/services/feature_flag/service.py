from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FeatureFlag, Role, User, UserRole
from ...time_utils import ensure_utc, utc_now
from ..admin.governance.admin_config_audit_service import record_admin_config_audit

FEATURE_FLAG_REASON_ENABLED = "enabled"
FEATURE_FLAG_REASON_DISABLED = "disabled"
FEATURE_FLAG_REASON_NOT_FOUND = "not_found"
FEATURE_FLAG_REASON_PROJECT_NOT_ALLOWED = "project_not_allowed"
FEATURE_FLAG_REASON_ROLE_NOT_ALLOWED = "role_not_allowed"
FEATURE_FLAG_REASON_ROLLOUT_EXCLUDED = "rollout_excluded"


def _normalize_flag_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_flag_key(value: Any) -> str:
    return _normalize_flag_text(value)


def _normalize_string_list(value: Any, *, field_name: str, lower: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, Iterable) and not isinstance(value, dict):
        items = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} entries must be strings")
            items.append(item.strip())
    else:
        raise ValueError(f"{field_name} must be a string or list of strings")
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        candidate = item.lower() if lower else item
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _normalize_enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("enabled must be a boolean")
    return value


def _normalize_rollout_percentage(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("rollout_percentage must be between 0 and 100")
    try:
        rollout_percentage = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("rollout_percentage must be between 0 and 100") from exc
    if rollout_percentage < 0 or rollout_percentage > 100:
        raise ValueError("rollout_percentage must be between 0 and 100")
    return rollout_percentage


def _feature_flag_outcome(*, key: str, reason: str, enabled: bool) -> dict[str, Any]:
    """The answer of the public evaluation: the flag's key, whether it is on for the caller, and why. The flag's
    configuration (its Workspace and role allowlists) stays on the admin surface: any signed-in user evaluates."""
    return {"key": key, "enabled": enabled, "reason": reason}


def serialize_feature_flag(row: FeatureFlag) -> dict[str, Any]:
    return {
        "id": row.id,
        "key": row.key,
        "description": row.description,
        "enabled": bool(row.enabled),
        "rollout_percentage": int(row.rollout_percentage or 0),
        "allowed_projects": _normalize_string_list(row.allowed_projects, field_name="allowed_projects"),
        "allowed_roles": _normalize_string_list(row.allowed_roles, field_name="allowed_roles", lower=True),
        "created_at": ensure_utc(row.created_at).isoformat() if row.created_at else None,
        "updated_at": ensure_utc(row.updated_at).isoformat() if row.updated_at else None,
    }


async def list_feature_flags(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(FeatureFlag).order_by(FeatureFlag.key.asc()))).scalars().all()
    return [serialize_feature_flag(row) for row in rows]


async def upsert_feature_flag(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    key = _normalize_flag_key(payload.get("key"))
    if not key:
        raise ValueError("key is required")
    row = (await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(key=key)
        db.add(row)
        before_audit = None
    else:
        before_audit = serialize_feature_flag(row)
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    if "enabled" in payload:
        row.enabled = _normalize_enabled(payload.get("enabled"))
    if "rollout_percentage" in payload and payload.get("rollout_percentage") is not None:
        row.rollout_percentage = _normalize_rollout_percentage(payload.get("rollout_percentage"))
    if "allowed_projects" in payload:
        row.allowed_projects = _normalize_string_list(payload.get("allowed_projects"), field_name="allowed_projects")
    if "allowed_roles" in payload:
        row.allowed_roles = _normalize_string_list(
            payload.get("allowed_roles"),
            field_name="allowed_roles",
            lower=True,
        )
    row.updated_at = utc_now()
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.security.feature_flag.saved",
        resource_type="feature_flag",
        resource_id=row.key,
        before=before_audit,
        after=serialize_feature_flag(row),
        details={
            "operation": "upsert_feature_flag",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    await db.refresh(row)
    return serialize_feature_flag(row)


async def delete_feature_flag(
    db: AsyncSession,
    *,
    key: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    key = _normalize_flag_key(key)
    row = (await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    if row is None:
        raise ValueError("Feature flag not found")
    before_audit = serialize_feature_flag(row)
    await db.delete(row)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.security.feature_flag.deleted",
        resource_type="feature_flag",
        resource_id=key,
        before=before_audit,
        after=None,
        details={"operation": "delete_feature_flag"},
    )
    await db.commit()
    return {"status": "deleted", "key": key}


async def _user_role_names(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {str(row[0]).strip().lower() for row in rows.all() if str(row[0] or "").strip()}


def _passes_rollout(*, key: str, user_id: str, project_id: str | None, rollout_percentage: int) -> bool:
    if rollout_percentage >= 100:
        return True
    if rollout_percentage <= 0:
        return False
    digest = hashlib.sha256(f"{key}:{user_id}:{project_id or ''}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < rollout_percentage


async def evaluate_feature_flag(
    db: AsyncSession,
    *,
    key: str,
    current_user: User,
    project_id: str | None = None,
) -> dict[str, Any]:
    key = _normalize_flag_key(key)
    project_id = _normalize_flag_text(project_id) or None
    row = (await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    if row is None:
        return _feature_flag_outcome(key=key, enabled=False, reason=FEATURE_FLAG_REASON_NOT_FOUND)
    payload = serialize_feature_flag(row)
    if not payload["enabled"]:
        return _feature_flag_outcome(
            key=payload["key"],
            enabled=False,
            reason=FEATURE_FLAG_REASON_DISABLED,
        )
    allowed_projects = payload["allowed_projects"]
    if allowed_projects:
        if not project_id or project_id not in allowed_projects:
            return _feature_flag_outcome(
                key=payload["key"],
                enabled=False,
                reason=FEATURE_FLAG_REASON_PROJECT_NOT_ALLOWED,
            )
    allowed_roles = payload["allowed_roles"]
    if allowed_roles:
        user_roles = await _user_role_names(db, current_user.id)
        if not user_roles.intersection(set(allowed_roles)):
            return _feature_flag_outcome(
                key=payload["key"],
                enabled=False,
                reason=FEATURE_FLAG_REASON_ROLE_NOT_ALLOWED,
            )
    if not _passes_rollout(
        key=payload["key"],
        user_id=current_user.id,
        project_id=project_id,
        rollout_percentage=payload["rollout_percentage"],
    ):
        return _feature_flag_outcome(
            key=payload["key"],
            enabled=False,
            reason=FEATURE_FLAG_REASON_ROLLOUT_EXCLUDED,
        )
    return _feature_flag_outcome(
        key=payload["key"],
        enabled=True,
        reason=FEATURE_FLAG_REASON_ENABLED,
    )
