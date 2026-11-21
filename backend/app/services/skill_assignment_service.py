from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import CapabilityType, Project, Skill, SkillVersion, WorkspaceCapabilityBinding, WorkspacePolicy
from ..models.runtime.governed_revision import REVISION_STATE_PUBLISHED
from .skill_catalog.extension import SURFACE_PLATFORM_CHAT, normalize_extension
from .workspace_composition.service import seed_workspace_bundle_foundation

PROJECT_SKILL_ASSIGNMENT_MODES = {"all_active", "selected_only", "none"}
# The Workspace assignment is the only grant; an agent narrows it (preferred ranks, blocked hides).
AGENT_SKILL_PREFERENCE_KEYS = ("preferred_skill_ids", "blocked_skill_ids")


async def get_project_skill_assignments(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    project = await _load_project_with_policy(db, project_id=project_id)
    skills = (
        (await db.execute(select(Skill).order_by(Skill.category.asc(), Skill.name.asc())))
        .scalars()
        .all()
    )
    published = await _published_versions(db, [skill.id for skill in skills])
    policy = _project_skill_policy(project.workspace_policy)
    bindings = await _load_skill_bindings(db, project_id=project.id)
    selected_skill_ids = sorted(
        {
            str(binding.source_entity_id or "").strip()
            for binding in bindings
            if binding.is_enabled and binding.binding_status != "hidden" and str(binding.source_entity_id or "").strip()
        }
    )
    return {
        "project_id": project.id,
        "policy": policy,
        "selected_skill_ids": selected_skill_ids,
        "skills": [_serialize_project_skill(skill, published.get(skill.id)) for skill in skills],
    }


async def update_project_skill_assignments(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    project = await _load_project_with_policy(db, project_id=project_id)
    policy = _project_skill_policy(project.workspace_policy)
    if "assignment_mode" in payload:
        policy["assignment_mode"] = _normalize_assignment_mode(payload.get("assignment_mode"))
    if "blocked_skill_ids" in payload:
        policy["blocked_skill_ids"] = _normalize_string_list(payload.get("blocked_skill_ids"))
    selected_skills: list[Skill] | None = None
    if "selected_skill_ids" in payload:
        selected_skill_ids = _normalize_string_list(payload.get("selected_skill_ids"))
        selected_skills = await _load_skills_by_ids(db, selected_skill_ids)

    routing_policy = dict(project.workspace_policy.routing_policy or {})
    routing_policy["skill_assignment_mode"] = policy["assignment_mode"]
    routing_policy["blocked_skill_keys"] = policy["blocked_skill_ids"]
    project.workspace_policy.routing_policy = routing_policy

    if selected_skills is not None:
        await _sync_project_skill_bindings(db, project=project, selected_skills=selected_skills)
    await db.commit()
    return await get_project_skill_assignments(db, project_id=project.id)


def normalize_agent_skill_preferences(value: Any) -> dict[str, list[str]]:
    raw = dict(value) if isinstance(value, dict) else {}
    return {key: _normalize_string_list(raw.get(key)) for key in AGENT_SKILL_PREFERENCE_KEYS}


def project_skill_policy_from_mapping(value: Any) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {}
    return {
        "assignment_mode": _normalize_assignment_mode(raw.get("skill_assignment_mode") or raw.get("assignment_mode")),
        "blocked_skill_ids": _normalize_string_list(raw.get("blocked_skill_keys") or raw.get("blocked_skill_ids")),
    }


async def _load_project_with_policy(db: AsyncSession, *, project_id: str) -> Project:
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await seed_workspace_bundle_foundation(db, workspace_id=project_id)
    project = (
        await db.execute(
            select(Project)
            .options(
                selectinload(Project.workspace_policy),
                selectinload(Project.workspace_capability_bindings).selectinload(
                    WorkspaceCapabilityBinding.capability_type
                ),
            )
            .where(Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_policy is None:
        raise HTTPException(status_code=500, detail="Workspace policy missing")
    return project


def _project_skill_policy(policy: WorkspacePolicy | None) -> dict[str, Any]:
    return project_skill_policy_from_mapping(policy.routing_policy if policy is not None else {})


async def _load_skill_bindings(db: AsyncSession, *, project_id: str) -> list[WorkspaceCapabilityBinding]:
    result = await db.execute(
        select(WorkspaceCapabilityBinding).where(
            WorkspaceCapabilityBinding.workspace_id == project_id,
            WorkspaceCapabilityBinding.capability_kind == "skill",
        )
    )
    return list(result.scalars().all())


async def _sync_project_skill_bindings(
    db: AsyncSession,
    *,
    project: Project,
    selected_skills: list[Skill],
) -> None:
    existing_by_key = {
        binding.binding_key: binding
        for binding in await _load_skill_bindings(db, project_id=project.id)
    }
    selected_keys = {f"skill:{skill.id}" for skill in selected_skills}
    for binding in existing_by_key.values():
        if binding.binding_key not in selected_keys:
            binding.is_enabled = False
            binding.binding_status = "hidden"

    published = await _published_versions(db, [skill.id for skill in selected_skills])
    for skill in selected_skills:
        capability_type = await _ensure_skill_capability_type(db, skill, published.get(skill.id))
        binding_key = f"skill:{skill.id}"
        binding = existing_by_key.get(binding_key)
        if binding is None:
            binding = WorkspaceCapabilityBinding(
                id=str(uuid.uuid4()),
                workspace_id=project.id,
                capability_type_id=capability_type.id,
                capability_kind="skill",
                binding_key=binding_key,
            )
            db.add(binding)
        binding.capability_type = capability_type
        binding.display_name = skill.name
        binding.binding_status = "active"
        binding.is_enabled = True
        binding.source_entity_type = "skill"
        binding.source_entity_id = skill.id


async def _published_versions(db: AsyncSession, skill_ids: list[str]) -> dict[str, SkillVersion]:
    if not skill_ids:
        return {}
    rows = await db.execute(
        select(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids), SkillVersion.state == REVISION_STATE_PUBLISHED)
    )
    return {row.skill_id: row for row in rows.scalars()}


def _description(published: SkillVersion | None) -> str:
    return str(((published.frontmatter if published is not None else None) or {}).get("description") or "")


async def _ensure_skill_capability_type(
    db: AsyncSession, skill: Skill, published: SkillVersion | None
) -> CapabilityType:
    key = f"skill:{skill.id}"
    lifecycle_status = "active" if published is not None else "draft"
    existing = (
        await db.execute(select(CapabilityType).where(CapabilityType.kind == "skill", CapabilityType.key == key))
    ).scalar_one_or_none()
    if existing is not None:
        existing.name = skill.name
        existing.description = _description(published)
        existing.lifecycle_status = lifecycle_status
        existing.is_active = published is not None
        return existing
    capability_type = CapabilityType(
        id=str(uuid.uuid4()),
        kind="skill",
        key=key,
        name=skill.name,
        description=_description(published),
        lifecycle_status=lifecycle_status,
        is_active=published is not None,
        contract={"source": skill.source, "category": skill.category},
    )
    db.add(capability_type)
    return capability_type


async def _load_skills_by_ids(db: AsyncSession, skill_ids: list[str]) -> list[Skill]:
    if not skill_ids:
        return []
    result = await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
    skills = list(result.scalars().all())
    found_ids = {skill.id for skill in skills}
    missing = sorted(set(skill_ids) - found_ids)
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown skill ids: {', '.join(missing)}")
    return skills


def _serialize_project_skill(skill: Skill, published: SkillVersion | None) -> dict[str, Any]:
    tools = normalize_extension(published.extension)["tools"][SURFACE_PLATFORM_CHAT] if published else {}
    return {
        "id": skill.id,
        "name": skill.name,
        "summary": _description(published),
        "category": skill.category,
        "status": "active" if published is not None else "draft",
        "source": skill.source,
        "version": int(published.version) if published is not None else None,
        "required_tools": list(tools.get("required") or []),
    }


def _normalize_assignment_mode(value: Any) -> str:
    normalized = str(value or "all_active").strip().lower()
    if normalized not in PROJECT_SKILL_ASSIGNMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid skill assignment mode")
    return normalized


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized
