"""Serialization and loading of research policy profiles and versions."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import ResearchPolicyProfile, ResearchPolicyProfileVersion
from ._admin_research_policy_spec import _as_dict, _iso, validate_research_policy_spec


def _serialize_version(version: ResearchPolicyProfileVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "profile_id": version.profile_id,
        "version": int(version.version or 0),
        "status": version.status,
        "spec": _as_dict(version.spec),
        "notes": version.notes or "",
        "diagnostics": validate_research_policy_spec(_as_dict(version.spec)),
        "created_by_user_id": version.created_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "published_at": _iso(version.published_at),
        "created_at": _iso(version.created_at),
        "updated_at": _iso(version.updated_at),
    }


def _serialize_profile(profile: ResearchPolicyProfile) -> dict[str, Any]:
    versions = sorted(profile.versions or [], key=lambda item: int(item.version or 0), reverse=True)
    published = [item for item in versions if item.status == "published"]
    return {
        "id": profile.id,
        "key": profile.key,
        "name": profile.name,
        "description": profile.description or "",
        "lifecycle_status": profile.lifecycle_status,
        "is_active": bool(profile.is_active),
        "created_by_user_id": profile.created_by_user_id,
        "created_at": _iso(profile.created_at),
        "updated_at": _iso(profile.updated_at),
        "latest_published_version_id": published[0].id if published else None,
        "versions": [_serialize_version(version) for version in versions],
    }


async def _get_profile(db: AsyncSession, profile_id: str) -> ResearchPolicyProfile:
    profile = (
        await db.execute(
            select(ResearchPolicyProfile)
            .options(selectinload(ResearchPolicyProfile.versions))
            .where(ResearchPolicyProfile.id == profile_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Research policy profile not found")
    return profile


async def _get_version(db: AsyncSession, version_id: str) -> ResearchPolicyProfileVersion:
    version = (
        await db.execute(
            select(ResearchPolicyProfileVersion)
            .options(selectinload(ResearchPolicyProfileVersion.profile))
            .where(ResearchPolicyProfileVersion.id == version_id)
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Research policy version not found")
    return version
