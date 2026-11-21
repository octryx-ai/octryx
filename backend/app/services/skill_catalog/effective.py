"""The effective skill set of a Workspace and surface — one function for chat and octryx-claude.

Deterministic order of filters:

1. published versions only;
2. the version's availability flag for the surface, and the Workspace surface switch
   (``runtime_policy.skill_surfaces``, both on by default);
3. the Workspace mode: ``all_active`` (all published), ``selected_only`` (the selected skills plus every skill
   published into a selected category or one of its children — later skills included), ``none``;
4. a skill a plugin brought only where that plugin is installed and active (``plugins/reach``);
5. minus the Workspace's blocked skills, minus the agent's blocked skills (chat), then the user's roles against
   the version's ``allowed_roles``.

Each skill that is not delivered keeps the reason, for the readiness view and the usage trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Skill, SkillCategory, SkillVersion, WorkspaceCapabilityBinding, WorkspacePolicy
from .extension import SURFACE_PLATFORM_CHAT, SURFACES, normalize_extension

KIND_SKILL_BINDING = "skill"
KIND_CATEGORY_BINDING = "skill_category"
CATEGORY_BINDING_PREFIX = "skill_category:"
MODES = ("all_active", "selected_only", "none")


@dataclass(slots=True)
class WorkspaceSkillPolicy:
    mode: str = "all_active"
    skill_ids: set[str] = field(default_factory=set)
    category_keys: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    surfaces: dict[str, bool] = field(default_factory=lambda: {surface: True for surface in SURFACES})

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "skill_ids": sorted(self.skill_ids), "category_keys": sorted(self.category_keys),
                "blocked_skill_ids": sorted(self.blocked), "surfaces": dict(self.surfaces)}


@dataclass(frozen=True, slots=True)
class Candidate:
    skill: Skill
    version: SkillVersion
    category: SkillCategory | None
    parent: SkillCategory | None
    delivered: bool
    reason: str
    assigned_by: str  # "all" | "skill" | "category:<key>" | ""


def surfaces_of(runtime_policy: Any) -> dict[str, bool]:
    raw = (runtime_policy or {}).get("skill_surfaces") if isinstance(runtime_policy, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {surface: raw.get(surface) is not False for surface in SURFACES}


async def workspace_policy(db: AsyncSession, project_id: str | None) -> WorkspaceSkillPolicy:
    if not project_id:
        return WorkspaceSkillPolicy()
    row = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project_id))
           ).scalar_one_or_none()
    routing = dict(row.routing_policy or {}) if row is not None else {}
    mode = str(routing.get("skill_assignment_mode") or "all_active")
    blocked = {str(item) for item in routing.get("blocked_skill_keys") or [] if str(item).strip()}
    bindings = (await db.execute(select(WorkspaceCapabilityBinding).where(
        WorkspaceCapabilityBinding.workspace_id == project_id,
        WorkspaceCapabilityBinding.capability_kind.in_([KIND_SKILL_BINDING, KIND_CATEGORY_BINDING]),
        WorkspaceCapabilityBinding.is_enabled.is_(True),
        WorkspaceCapabilityBinding.binding_status != "hidden"))).scalars().all()
    skill_ids = {str(item.source_entity_id) for item in bindings
                 if item.capability_kind == KIND_SKILL_BINDING and item.source_entity_id}
    category_keys = {str(item.binding_key)[len(CATEGORY_BINDING_PREFIX):] for item in bindings
                     if item.capability_kind == KIND_CATEGORY_BINDING
                     and str(item.binding_key).startswith(CATEGORY_BINDING_PREFIX)}
    return WorkspaceSkillPolicy(mode=mode if mode in MODES else "none", skill_ids=skill_ids,
                                category_keys=category_keys, blocked=blocked,
                                surfaces=surfaces_of(row.runtime_policy if row is not None else None))


def _keys(skill: Skill) -> set[str]:
    return {skill.id, skill.name, f"skill:{skill.id}"}


def _agent_blocked(agent_definition: dict[str, Any] | None) -> set[str]:
    raw = (agent_definition or {}).get("skillPreferences") or (agent_definition or {}).get("skill_preferences")
    blocked = raw.get("blocked_skill_ids") if isinstance(raw, dict) else None
    return {str(item) for item in blocked or [] if str(item).strip()}


async def candidates(db: AsyncSession, *, project_id: str | None, surface: str,
                     user_roles: list[str] | None = None, agent_definition: dict[str, Any] | None = None,
                     policy: WorkspaceSkillPolicy | None = None) -> list[Candidate]:
    """Every published skill with its delivery decision for this Workspace, surface, user and agent."""
    policy = policy or await workspace_policy(db, project_id)
    rows = (await db.execute(select(Skill, SkillVersion).join(SkillVersion, SkillVersion.skill_id == Skill.id)
                             .where(SkillVersion.state == "published").order_by(Skill.name))).all()
    categories = {row.id: row for row in (await db.execute(select(SkillCategory))).scalars()}
    roles = {str(role).strip().lower() for role in user_roles or [] if str(role).strip()}
    agent_blocked = _agent_blocked(agent_definition) if surface == SURFACE_PLATFORM_CHAT else set()
    from ..plugins.reach import outside_reach, skill_reach

    plugin_reach = await skill_reach(db)
    found: list[Candidate] = []
    for skill, version in rows:
        category = categories.get(version.category_id or "")
        parent = categories.get(category.parent_id) if category is not None and category.parent_id else None
        by_category = next((key for key in (category.key if category else None, parent.key if parent else None)
                            if key and key in policy.category_keys), None)
        assigned_by = ("all" if policy.mode == "all_active" else "skill" if skill.id in policy.skill_ids
                       else f"category:{by_category}" if by_category else "")
        flag = version.available_platform_chat if surface == SURFACE_PLATFORM_CHAT else version.available_octryx_claude
        allowed_roles = set(normalize_extension(version.extension)["allowed_roles"])
        # An MCP server entry is never available on platform chat (a write-time invariant, versions.py).
        reason = (
            "plugin_not_installed_here" if outside_reach(plugin_reach, skill.id, project_id)
            else "not_available_on_surface" if not flag
            else "surface_off_for_workspace" if not policy.surfaces.get(surface, True)
            else "skills_off_for_workspace" if policy.mode == "none"
            else "not_assigned" if not assigned_by
            else "blocked_by_workspace" if _keys(skill) & policy.blocked
            else "blocked_by_agent" if _keys(skill) & agent_blocked
            else "role_not_allowed" if user_roles is not None and allowed_roles and not allowed_roles & roles
            else ""
        )
        found.append(Candidate(skill, version, category, parent, delivered=not reason, reason=reason,
                               assigned_by=assigned_by))
    return found


async def effective_skills(db: AsyncSession, *, project_id: str | None, surface: str,
                           user_roles: list[str] | None = None,
                           agent_definition: dict[str, Any] | None = None) -> list[Candidate]:
    return [item for item in await candidates(db, project_id=project_id, surface=surface, user_roles=user_roles,
                                              agent_definition=agent_definition) if item.delivered]


__all__ = [
    "CATEGORY_BINDING_PREFIX",
    "KIND_CATEGORY_BINDING",
    "KIND_SKILL_BINDING",
    "MODES",
    "Candidate",
    "WorkspaceSkillPolicy",
    "candidates",
    "effective_skills",
    "surfaces_of",
    "workspace_policy",
]
