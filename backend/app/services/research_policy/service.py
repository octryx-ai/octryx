from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    ResearchPolicyProfile,
    ResearchPolicyProfileVersion,
    WorkspaceResearchPolicyAssignment,
)
from ...time_utils import utc_now
from .defaults import default_research_policy_profiles

DEFAULT_RESEARCH_POLICY_KEY = "deep-research-document"


async def ensure_default_research_policy_profiles(db: AsyncSession) -> None:
    """Seed built-in research profiles without overwriting admin-managed versions."""

    for payload in default_research_policy_profiles():
        key = str(payload["key"])
        profile = (
            await db.execute(select(ResearchPolicyProfile).where(ResearchPolicyProfile.key == key))
        ).scalar_one_or_none()
        if profile is None:
            profile = ResearchPolicyProfile(
                id=str(uuid.uuid4()),
                key=key,
                name=str(payload["name"]),
                description=str(payload.get("description") or ""),
                lifecycle_status="active",
                is_active=True,
            )
            db.add(profile)
            await db.flush()

        version_number = int(payload.get("version") or 1)
        version = (
            await db.execute(
                select(ResearchPolicyProfileVersion).where(
                    ResearchPolicyProfileVersion.profile_id == profile.id,
                    ResearchPolicyProfileVersion.version == version_number,
                )
            )
        ).scalar_one_or_none()
        if version is not None:
            continue
        db.add(
            ResearchPolicyProfileVersion(
                id=str(uuid.uuid4()),
                profile_id=profile.id,
                version=version_number,
                status=str(payload.get("status") or "published"),
                spec=payload.get("spec") or {},
                notes="Seeded default research policy profile.",
                published_at=utc_now(),
            )
        )
    await db.flush()


def _as_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def serialize_research_policy_resolution(
    *,
    profile: ResearchPolicyProfile,
    version: ResearchPolicyProfileVersion,
    source: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "profile_id": str(profile.id or ""),
        "profile_key": str(profile.key or ""),
        "profile_name": str(profile.name or ""),
        "version_id": str(version.id or ""),
        "version": int(version.version or 0),
        "status": str(version.status or ""),
        "spec": _as_dict(version.spec),
    }


async def resolve_effective_research_policy(
    db: AsyncSession,
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    await ensure_default_research_policy_profiles(db)
    normalized_workspace_id = str(workspace_id or "").strip()
    if normalized_workspace_id:
        assignment = (
            await db.execute(
                select(WorkspaceResearchPolicyAssignment)
                .options(
                    selectinload(WorkspaceResearchPolicyAssignment.profile_version).selectinload(
                        ResearchPolicyProfileVersion.profile
                    )
                )
                .where(
                    WorkspaceResearchPolicyAssignment.workspace_id == normalized_workspace_id,
                    WorkspaceResearchPolicyAssignment.assignment_status == "active",
                )
            )
        ).scalar_one_or_none()
        if (
            assignment is not None
            and assignment.profile_version is not None
            and assignment.profile_version.profile is not None
            and assignment.profile_version.status == "published"
        ):
            return serialize_research_policy_resolution(
                profile=assignment.profile_version.profile,
                version=assignment.profile_version,
                source="workspace_assignment",
            )

    version = (
        await db.execute(
            select(ResearchPolicyProfileVersion)
            .join(ResearchPolicyProfile)
            .options(selectinload(ResearchPolicyProfileVersion.profile))
            .where(
                ResearchPolicyProfile.key == DEFAULT_RESEARCH_POLICY_KEY,
                ResearchPolicyProfile.is_active.is_(True),
                ResearchPolicyProfileVersion.status == "published",
            )
            .order_by(ResearchPolicyProfileVersion.version.desc())
        )
    ).scalars().first()
    if version is None or version.profile is None:
        return {}
    return serialize_research_policy_resolution(
        profile=version.profile,
        version=version,
        source="default_profile",
    )


__all__ = [
    "DEFAULT_RESEARCH_POLICY_KEY",
    "ensure_default_research_policy_profiles",
    "resolve_effective_research_policy",
    "serialize_research_policy_resolution",
]
