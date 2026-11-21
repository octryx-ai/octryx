"""Admin-panel service helpers for scenario profile management flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, ScenarioProfile
from ...scenario_profile.unsupported_fields import refuse_unsupported_scenario_fields


async def list_scenarios(
    db: AsyncSession,
    *,
    user_id: str,
    serialize_profile: Callable[[ScenarioProfile], dict[str, Any]],
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(ScenarioProfile)
        .where(ScenarioProfile.owner_id == user_id)
        .order_by(ScenarioProfile.priority.desc(), ScenarioProfile.updated_at.desc())
    )
    return [serialize_profile(profile) for profile in result.scalars().all()]


async def create_scenario(
    db: AsyncSession,
    *,
    user_id: str,
    payload: dict[str, Any],
    serialize_profile: Callable[[ScenarioProfile], dict[str, Any]],
) -> dict[str, Any]:
    refuse_unsupported_scenario_fields(payload)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    project_id = str(payload.get("project_id") or "").strip() or None
    if project_id and not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    profile = ScenarioProfile(
        owner_id=user_id,
        project_id=project_id,
        name=name,
        description=str(payload.get("description") or ""),
        priority=int(payload.get("priority") or 100),
        match_config=payload.get("match_config") or {},
        planner_config=payload.get("planner_config") or {},
        execution_config=payload.get("execution_config") or {},
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return serialize_profile(profile)


async def update_scenario(
    db: AsyncSession,
    *,
    user_id: str,
    scenario_id: str,
    payload: dict[str, Any],
    serialize_profile: Callable[[ScenarioProfile], dict[str, Any]],
) -> dict[str, Any]:
    refuse_unsupported_scenario_fields(payload)
    profile = (
        await db.execute(
            select(ScenarioProfile).where(ScenarioProfile.id == scenario_id, ScenarioProfile.owner_id == user_id)
        )
    ).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Scenario profile not found")
    if "name" in payload:
        profile.name = str(payload.get("name") or "").strip() or profile.name
    if "description" in payload:
        profile.description = str(payload.get("description") or "")
    if "priority" in payload:
        profile.priority = int(payload.get("priority") or 100)
    if "project_id" in payload:
        project_id = str(payload.get("project_id") or "").strip() or None
        if project_id and not await db.get(Project, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        profile.project_id = project_id
    if "match_config" in payload:
        profile.match_config = payload.get("match_config") or {}
    if "planner_config" in payload:
        profile.planner_config = payload.get("planner_config") or {}
    if "execution_config" in payload:
        profile.execution_config = payload.get("execution_config") or {}
    if "is_active" in payload:
        profile.is_active = bool(payload.get("is_active"))
    await db.commit()
    await db.refresh(profile)
    return serialize_profile(profile)


async def delete_scenario(db: AsyncSession, *, user_id: str, scenario_id: str) -> dict[str, Any]:
    profile = (
        await db.execute(
            select(ScenarioProfile).where(ScenarioProfile.id == scenario_id, ScenarioProfile.owner_id == user_id)
        )
    ).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Scenario profile not found")
    await db.delete(profile)
    await db.commit()
    return {"status": "deleted"}
