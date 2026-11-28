"""Per-Workspace skill assignment incl. whole categories and surfaces."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AuditLog,
    CapabilityType,
    Project,
    Skill,
    SkillCategory,
    WorkspaceCapabilityBinding,
    WorkspacePolicy,
)
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER
from ...time_utils import utc_now
from ..skill_assignment_service import _load_project_with_policy, _sync_project_skill_bindings
from .categories import tree
from .effective import (
    CATEGORY_BINDING_PREFIX,
    KIND_CATEGORY_BINDING,
    MODES,
    WorkspaceSkillPolicy,
    candidates,
    workspace_policy,
)
from .errors import SkillCatalogError
from .extension import SURFACES
from .lifecycle import etag
from .readiness import readiness

AUDIT_ASSIGNMENT_SAVED = "skill_catalog.assignment_saved"


def assignment_digest(policy: WorkspaceSkillPolicy) -> str:
    encoded = json.dumps(policy.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _category_path(candidate) -> list[str]:
    if candidate.category is None:
        return []
    return [candidate.parent.label, candidate.category.label] if candidate.parent else [candidate.category.label]


async def assignment_view(db: AsyncSession, project_id: str) -> dict[str, Any]:
    project = await _load_project_with_policy(db, project_id=project_id)
    policy = await workspace_policy(db, project.id)
    effective: dict[str, list[dict[str, Any]]] = {}
    withheld: dict[str, list[dict[str, Any]]] = {}
    catalog: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        effective[surface], withheld[surface] = [], []
        for item in await candidates(db, project_id=project.id, surface=surface, policy=policy):
            catalog.setdefault(item.skill.id, {
                "id": item.skill.id, "name": item.skill.name, "kind": item.skill.kind,
                "description": str((item.version.frontmatter or {}).get("description") or ""),
                "version": item.version.version, "category_key": item.category.key if item.category else None,
                "category_path": _category_path(item)})
            row = {"skill_id": item.skill.id, "name": item.skill.name, "kind": item.skill.kind,
                   "version": item.version.version, "category_path": _category_path(item),
                   "assigned_by": item.assigned_by}
            if item.delivered:
                effective[surface].append({**row, "readiness": readiness(item, project, surface)})
            elif item.assigned_by and not (item.skill.kind == SKILL_KIND_MCP_SERVER and surface == "platform_chat"):
                # assigned, yet not delivered (an MCP entry is never a chat skill, so it is not "withheld" there)
                withheld[surface].append({**row, "reason": item.reason})
    return {"project_id": project.id, "digest": assignment_digest(policy), "policy": policy.as_dict(),
            "categories": await tree(db, include_archived=False), "skills": sorted(catalog.values(),
                                                                                  key=lambda row: row["name"]),
            "effective": effective, "withheld": withheld}


async def _ensure_category_type(db: AsyncSession, category: SkillCategory) -> CapabilityType:
    key = f"{CATEGORY_BINDING_PREFIX}{category.key}"
    existing = (await db.execute(select(CapabilityType).where(CapabilityType.kind == KIND_CATEGORY_BINDING,
                                                              CapabilityType.key == key))).scalar_one_or_none()
    if existing is not None:
        existing.name = category.label
        return existing
    created = CapabilityType(id=str(uuid.uuid4()), kind=KIND_CATEGORY_BINDING, key=key, name=category.label,
                             description=category.description or "", lifecycle_status="active", is_active=True,
                             contract={"category_key": category.key})
    db.add(created)
    return created


async def _sync_category_bindings(db: AsyncSession, project: Project, chosen: list[SkillCategory]) -> None:
    existing = {row.binding_key: row for row in (await db.execute(select(WorkspaceCapabilityBinding).where(
        WorkspaceCapabilityBinding.workspace_id == project.id,
        WorkspaceCapabilityBinding.capability_kind == KIND_CATEGORY_BINDING))).scalars()}
    wanted = {f"{CATEGORY_BINDING_PREFIX}{category.key}": category for category in chosen}
    for key, binding in existing.items():
        if key not in wanted:
            binding.is_enabled, binding.binding_status = False, "hidden"
    for key, category in wanted.items():
        capability_type = await _ensure_category_type(db, category)
        binding = existing.get(key)
        if binding is None:
            binding = WorkspaceCapabilityBinding(id=str(uuid.uuid4()), workspace_id=project.id,
                                                 capability_type_id=capability_type.id,
                                                 capability_kind=KIND_CATEGORY_BINDING, binding_key=key)
            db.add(binding)
        binding.capability_type = capability_type
        binding.display_name, binding.binding_status, binding.is_enabled = category.label, "active", True
        binding.source_entity_type, binding.source_entity_id = "skill_category", category.id


def _validated(payload: dict[str, Any]) -> tuple[str, list[str], list[str], list[str], dict[str, bool]]:
    mode = str(payload.get("mode") or "")
    if mode not in MODES:
        raise SkillCatalogError("skill_assignment_mode_invalid", 422, modes=list(MODES))
    surfaces = payload.get("surfaces") if isinstance(payload.get("surfaces"), dict) else {}

    def strings(key: str) -> list[str]:
        value = payload.get(key)
        return sorted({str(item) for item in value if str(item).strip()}) if isinstance(value, list) else []

    return (mode, strings("skill_ids"), strings("category_keys"), strings("blocked_skill_ids"),
            {surface: surfaces.get(surface) is not False for surface in SURFACES})


async def save_assignment(db: AsyncSession, project_id: str, payload: dict[str, Any], *, if_match: str | None,
                          actor_id: str) -> dict[str, Any]:
    expected = etag(if_match)
    if not expected:
        raise SkillCatalogError("skill_assignment_if_match_required", 428)
    project = await _load_project_with_policy(db, project_id=project_id)
    current = await workspace_policy(db, project.id)
    if assignment_digest(current) != expected:
        raise SkillCatalogError("skill_assignment_conflict", 409, digest=assignment_digest(current))
    mode, skill_ids, category_keys, blocked, surfaces = _validated(payload)
    skills = list((await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))).scalars()) if skill_ids else []
    if {skill.id for skill in skills} != set(skill_ids):
        raise SkillCatalogError("skill_assignment_unknown_skill", 422,
                                skills=sorted(set(skill_ids) - {skill.id for skill in skills}))
    chosen = list((await db.execute(select(SkillCategory).where(SkillCategory.key.in_(category_keys),
                                                                SkillCategory.archived_at.is_(None)))).scalars()
                  ) if category_keys else []
    if {category.key for category in chosen} != set(category_keys):
        raise SkillCatalogError("skill_assignment_unknown_category", 422,
                                categories=sorted(set(category_keys) - {category.key for category in chosen}))
    policy_row: WorkspacePolicy = project.workspace_policy
    claimed = await db.execute(update(WorkspacePolicy).where(
        WorkspacePolicy.id == policy_row.id, WorkspacePolicy.updated_at == policy_row.updated_at
    ).values(updated_at=utc_now()).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        raise SkillCatalogError("skill_assignment_conflict", 409)
    await db.refresh(policy_row)
    routing = dict(policy_row.routing_policy or {})
    routing["skill_assignment_mode"], routing["blocked_skill_keys"] = mode, blocked
    policy_row.routing_policy = routing
    runtime = dict(policy_row.runtime_policy or {})
    runtime["skill_surfaces"] = surfaces
    policy_row.runtime_policy = runtime
    await _sync_project_skill_bindings(db, project=project, selected_skills=skills)
    await _sync_category_bindings(db, project, chosen)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ASSIGNMENT_SAVED, resource_type="project", resource_id=project.id,
                    details={"mode": mode, "skills": skill_ids, "categories": category_keys, "blocked": blocked,
                             "surfaces": surfaces}))
    await db.flush()
    return await assignment_view(db, project.id)


__all__ = ["AUDIT_ASSIGNMENT_SAVED", "assignment_digest", "assignment_view", "save_assignment"]
