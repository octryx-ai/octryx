"""Admin-panel service helpers for research policy management."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import ResearchPolicyProfile, ResearchPolicyProfileVersion
from ....services.research_policy import DEFAULT_RESEARCH_POLICY_KEY, ensure_default_research_policy_profiles
from ....time_utils import utc_now
from ._admin_research_policy_records import _get_profile, _get_version, _serialize_profile
from ._admin_research_policy_spec import (
    _PROFILE_KEY_PATTERN,
    _VALID_PROFILE_STATUSES,
    _VALID_VERSION_STATUSES,
    _as_dict,
    _require_valid_spec,
)


async def list_research_policies(db: AsyncSession) -> dict[str, Any]:
    await ensure_default_research_policy_profiles(db)
    profiles = (
        (
            await db.execute(
                select(ResearchPolicyProfile)
                .options(selectinload(ResearchPolicyProfile.versions))
                .order_by(ResearchPolicyProfile.key.asc())
            )
        )
        .scalars()
        .all()
    )
    serialized = [_serialize_profile(profile) for profile in profiles]
    invalid_versions = [
        version
        for profile in serialized
        for version in profile["versions"]
        if version["diagnostics"]["status"] != "valid"
    ]
    return {
        "profiles": serialized,
        "defaults": {"default_profile_key": DEFAULT_RESEARCH_POLICY_KEY},
        "diagnostics": {
            "status": "valid" if not invalid_versions else "invalid",
            "invalid_version_count": len(invalid_versions),
        },
    }


async def create_research_policy_profile(
    db: AsyncSession,
    *,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    key = str(payload.get("key") or "").strip()
    if not _PROFILE_KEY_PATTERN.match(key):
        raise HTTPException(status_code=400, detail="key must be lowercase slug text with at least 3 characters")
    existing = (
        await db.execute(select(ResearchPolicyProfile).where(ResearchPolicyProfile.key == key))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Research policy profile key already exists")
    status = str(payload.get("initial_version_status") or "draft").strip()
    if status not in _VALID_VERSION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid initial version status")
    spec = _as_dict(payload.get("initial_spec"))
    _require_valid_spec(spec)
    now = utc_now()
    profile = ResearchPolicyProfile(
        id=str(uuid.uuid4()),
        key=key,
        name=str(payload.get("name") or key).strip(),
        description=str(payload.get("description") or ""),
        lifecycle_status="active",
        is_active=True,
        created_by_user_id=admin_id,
    )
    version = ResearchPolicyProfileVersion(
        id=str(uuid.uuid4()),
        profile_id=profile.id,
        version=1,
        status=status,
        spec=spec,
        notes=str(payload.get("notes") or ""),
        created_by_user_id=admin_id,
        published_by_user_id=admin_id if status == "published" else None,
        published_at=now if status == "published" else None,
    )
    db.add_all([profile, version])
    await db.commit()
    return _serialize_profile(await _get_profile(db, profile.id))


async def update_research_policy_profile(
    db: AsyncSession,
    *,
    profile_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    profile = await _get_profile(db, profile_id)
    if "name" in payload:
        profile.name = str(payload.get("name") or "").strip() or profile.name
    if "description" in payload:
        profile.description = str(payload.get("description") or "")
    if "lifecycle_status" in payload:
        lifecycle_status = str(payload.get("lifecycle_status") or "").strip()
        if lifecycle_status not in _VALID_PROFILE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid lifecycle_status")
        profile.lifecycle_status = lifecycle_status
        profile.is_active = lifecycle_status == "active"
    if "is_active" in payload:
        profile.is_active = bool(payload.get("is_active"))
        if not profile.is_active and profile.lifecycle_status == "active":
            profile.lifecycle_status = "archived"
    await db.commit()
    return _serialize_profile(await _get_profile(db, profile.id))


async def delete_research_policy_profile(db: AsyncSession, *, profile_id: str) -> dict[str, Any]:
    profile = await _get_profile(db, profile_id)
    profile.is_active = False
    profile.lifecycle_status = "archived"
    await db.commit()
    return {"status": "archived", "profile_id": profile_id}


async def create_research_policy_version(
    db: AsyncSession,
    *,
    admin_id: str,
    profile_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _get_profile(db, profile_id)
    spec = _as_dict(payload.get("spec"))
    _require_valid_spec(spec)
    status = str(payload.get("status") or "draft").strip()
    if status not in _VALID_VERSION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid version status")
    next_version = (
        await db.execute(
            select(func.max(ResearchPolicyProfileVersion.version)).where(
                ResearchPolicyProfileVersion.profile_id == profile_id
            )
        )
    ).scalar_one()
    now = utc_now()
    version = ResearchPolicyProfileVersion(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        version=int(next_version or 0) + 1,
        status=status,
        spec=spec,
        notes=str(payload.get("notes") or ""),
        created_by_user_id=admin_id,
        published_by_user_id=admin_id if status == "published" else None,
        published_at=now if status == "published" else None,
    )
    db.add(version)
    await db.commit()
    return _serialize_profile(await _get_profile(db, profile_id))


async def update_research_policy_version(
    db: AsyncSession,
    *,
    admin_id: str,
    profile_id: str,
    version_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    version = await _get_version(db, version_id)
    if version.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="Research policy version not found")
    if "spec" in payload:
        if version.status == "published":
            raise HTTPException(status_code=400, detail="Published versions are immutable; create a new version")
        spec = _as_dict(payload.get("spec"))
        _require_valid_spec(spec)
        version.spec = spec
    if "notes" in payload:
        version.notes = str(payload.get("notes") or "")
    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        if status not in _VALID_VERSION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid version status")
        if status == "published":
            _require_valid_spec(_as_dict(version.spec))
            version.published_by_user_id = admin_id
            version.published_at = utc_now()
        version.status = status
    await db.commit()
    return _serialize_profile(await _get_profile(db, profile_id))


__all__ = [
    "create_research_policy_profile",
    "create_research_policy_version",
    "delete_research_policy_profile",
    "list_research_policies",
    "update_research_policy_profile",
    "update_research_policy_version",
]
