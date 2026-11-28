"""Project service helpers for resolving project access and configuration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    IdentityGroup,
    Project,
    ProjectGroup,
    ProjectGroupRoleAssignment,
    ProjectUserRoleAssignment,
    Role,
    UserGroup,
    UserProject,
    UserRole,
)
from ..runtime_policy_bundle import apply_runtime_policy_bundle
from ..tool_config import merge_tool_configs_into_project_config

DEFAULT_PROJECT_ACCESS_ROLE = "member"
PROJECT_ROLE_ACCESS_CONFIG_KEY = "role_access_assignments"


def _normalize_project_role(value: str | None) -> str | None:
    if not value:
        return None
    role = str(value).strip().lower()
    return role or None


def _normalize_project_roles(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    seen: set[str] = set()
    normalized: list[str] = []
    for item in values:
        role = _normalize_project_role(str(item) if item is not None else None)
        if not role or role in seen:
            continue
        seen.add(role)
        normalized.append(role)
    return normalized


def _has_explicit_project_roles(value: object | None) -> bool:
    return isinstance(value, (list, tuple, set)) and len(value) > 0


def _as_project_roles(raw_roles: object | None, fallback_role: str | None = None) -> list[str]:
    roles = _normalize_project_roles(raw_roles)
    if not roles and _has_explicit_project_roles(raw_roles):
        return [DEFAULT_PROJECT_ACCESS_ROLE]
    if not roles and fallback_role:
        return [fallback_role]
    if not roles:
        return [DEFAULT_PROJECT_ACCESS_ROLE]
    return roles


def _merge_project_roles(current_roles: list[str], extra_roles: list[str]) -> list[str]:
    seen: set[str] = set(current_roles)
    merged = list(current_roles)
    for role in extra_roles:
        if role in seen:
            continue
        merged.append(role)
        seen.add(role)
    return merged


def _update_group_names(payload: dict[str, object], group_name: str) -> None:
    current_group = payload.get("group")
    if not isinstance(current_group, str) or not current_group:
        payload["group"] = group_name
        return
    groups = {name.strip() for name in current_group.split(",") if name.strip()}
    groups.add(group_name)
    payload["group"] = ", ".join(sorted(groups))


def _merge_access_sources(existing: str | None, added: str) -> str:
    if not existing:
        return added
    if existing == added:
        return existing
    parts = [part.strip() for part in existing.split(",") if part.strip()]
    if added in parts:
        return ",".join(parts)
    if existing == "direct" and added == "group":
        return "direct,group"
    if existing == "group" and added == "direct":
        return "direct,group"
    if existing == "direct" and added == "role":
        return "direct,role"
    if existing == "role" and added == "direct":
        return "direct,role"
    if existing == "group" and added == "role":
        return "group,role"
    if existing == "role" and added == "group":
        return "group,role"
    if existing == "direct,group" and added == "role":
        return "direct,group,role"
    if existing == "direct,role" and added == "group":
        return "direct,group,role"
    if existing == "group,role" and added == "direct":
        return "direct,group,role"
    return existing + "," + added


def _role_access_project_roles(
    raw_config: object,
    user_roles: set[str],
    role_lookup: dict[str, str],
) -> list[str]:
    if not isinstance(raw_config, dict):
        return []
    assignments = raw_config.get(PROJECT_ROLE_ACCESS_CONFIG_KEY)
    if not isinstance(assignments, list):
        return []
    required_project_roles: list[str] = []
    seen = set()
    for item in assignments:
        if not isinstance(item, dict):
            continue
        role_id = str(item.get("role_id") or "").strip()
        role_name = role_lookup.get(role_id, _normalize_project_role(item.get("role") or ""))
        if not role_name:
            continue
        if role_name not in user_roles:
            continue
        project_roles = _as_project_roles(item.get("project_roles"), None)
        for role in project_roles:
            if role in seen:
                continue
            required_project_roles.append(role)
            seen.add(role)
    return required_project_roles


async def get_user_project_ids(user_id: str, db: AsyncSession) -> list[str]:
    """Get all project IDs a user has access to."""
    access = await get_project_access_details(user_id, db)
    return [item["id"] for item in access]


async def get_project_access_details(user_id: str, db: AsyncSession) -> list[dict[str, object]]:
    """Get direct and group-derived project access for a user."""
    direct_rows = await db.execute(
        select(
            Project.id,
            Project.name,
            ProjectUserRoleAssignment.role_name,
            UserProject.role,
        )
        .join(UserProject, UserProject.project_id == Project.id)
        .outerjoin(
            ProjectUserRoleAssignment,
            (ProjectUserRoleAssignment.user_id == UserProject.user_id)
            & (ProjectUserRoleAssignment.project_id == UserProject.project_id),
        )
        .where(UserProject.user_id == user_id)
        .order_by(Project.name.asc(), ProjectUserRoleAssignment.role_name.asc())
    )
    access_by_project: dict[str, dict[str, object]] = {}
    role_rows = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    user_roles = {_normalize_project_role(row[0]) for row in role_rows.all() if row[0] is not None}
    user_roles = {role for role in user_roles if role}
    role_rows = await db.execute(select(Role.id, Role.name))
    role_lookup: dict[str, str] = {}
    for role_id, role_name in role_rows.all():
        normalized = _normalize_project_role(role_name)
        if normalized is not None:
            role_lookup[role_id] = normalized

    direct_roles_by_project: dict[str, list[str]] = {}
    direct_fallback_by_project: dict[str, str | None] = {}
    direct_name_by_project: dict[str, str] = {}
    for project_id, project_name, role_name, fallback_role in direct_rows.all():
        direct_name_by_project[project_id] = project_name
        direct_fallback_by_project.setdefault(project_id, fallback_role)
        bucket = direct_roles_by_project.setdefault(project_id, [])
        if role_name is not None:
            bucket.append(role_name)
    for project_id, raw_roles in direct_roles_by_project.items():
        project_roles = _as_project_roles(raw_roles, direct_fallback_by_project.get(project_id))
        access_by_project[project_id] = {
            "id": project_id,
            "name": direct_name_by_project[project_id],
            "role": project_roles[0],
            "project_roles": project_roles,
            "source": "direct",
        }

    group_rows = await db.execute(
        select(
            Project.id,
            Project.name,
            ProjectGroupRoleAssignment.role_name,
            ProjectGroup.role,
            IdentityGroup.name,
        )
        .join(ProjectGroup, ProjectGroup.project_id == Project.id)
        .join(IdentityGroup, IdentityGroup.id == ProjectGroup.group_id)
        .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
        .outerjoin(
            ProjectGroupRoleAssignment,
            (ProjectGroupRoleAssignment.group_id == ProjectGroup.group_id)
            & (ProjectGroupRoleAssignment.project_id == ProjectGroup.project_id),
        )
        .where(
            UserGroup.user_id == user_id,
            IdentityGroup.is_active.is_(True),
            Project.is_active.is_(True),
        )
        .order_by(
            Project.name.asc(),
            IdentityGroup.name.asc(),
            ProjectGroupRoleAssignment.role_name.asc(),
        )
    )
    # Aggregate child role rows back into one entry per (project, group) grant,
    # preserving the original iteration order over (project name, group name).
    group_grants: list[tuple[str, str, list[str], str | None, str]] = []
    group_grant_index: dict[tuple[str, str], int] = {}
    for project_id, project_name, role_name, fallback_role, group_name in group_rows.all():
        key = (project_id, group_name)
        idx = group_grant_index.get(key)
        if idx is None:
            group_grant_index[key] = len(group_grants)
            group_grants.append((project_id, project_name, [], fallback_role, group_name))
            idx = group_grant_index[key]
        if role_name is not None:
            group_grants[idx][2].append(role_name)
    for project_id, project_name, raw_roles, fallback_role, group_name in group_grants:
        required_roles = _as_project_roles(raw_roles, fallback_role)
        if project_id in access_by_project:
            current = access_by_project[project_id]
            _update_group_names(current, group_name)
            if current.get("source") != "direct,group":
                current["source"] = "direct,group"
            current_roles = current.get("project_roles")
            if isinstance(current_roles, list):
                current["project_roles"] = _merge_project_roles(current_roles, required_roles)
                current_project_roles = current.get("project_roles")
                if isinstance(current_project_roles, list) and current_project_roles:
                    current["role"] = current_project_roles[0]
            continue
        access_by_project[project_id] = {
            "id": project_id,
            "name": project_name,
            "role": required_roles[0],
            "project_roles": required_roles,
            "source": "group",
            "group": group_name,
        }

    role_assignment_rows = await db.execute(
        select(Project.id, Project.name, Project.config)
        .where(Project.is_active.is_(True))
        .order_by(Project.name.asc())
    )
    for project_id, project_name, project_config in role_assignment_rows.all():
        required_roles = _role_access_project_roles(project_config, user_roles, role_lookup)
        if not required_roles:
            continue
        if project_id in access_by_project:
            current = access_by_project[project_id]
            current_roles = current.get("project_roles")
            if isinstance(current_roles, list):
                current["project_roles"] = _merge_project_roles(current_roles, required_roles)
                current_project_roles = current.get("project_roles")
                if isinstance(current_project_roles, list) and current_project_roles:
                    current["role"] = current_project_roles[0]
            current["source"] = _merge_access_sources(str(current.get("source") or ""), "role")
            continue
        access_by_project[project_id] = {
            "id": project_id,
            "name": project_name,
            "role": required_roles[0],
            "project_roles": required_roles,
            "source": "role",
        }
    # A private Workspace: only its owner, whatever memberships, groups or role rules say.
    from .private_workspace import OWNER_ROLE, hidden_private_ids, owned_private_workspace  # noqa: PLC0415

    for project_id in await hidden_private_ids(db, user_id):
        access_by_project.pop(project_id, None)
    own = await owned_private_workspace(db, user_id)
    if own is not None and own.id in access_by_project:
        access_by_project[own.id].update({"role": OWNER_ROLE, "project_roles": [OWNER_ROLE], "source": "direct",
                                          "private": True})
    return sorted(access_by_project.values(), key=lambda item: item["name"])


async def get_project_config(project_id: str | None, db: AsyncSession) -> dict:
    """Resolve the project configuration: ``Project.config`` merged with the tool configs."""
    if not project_id:
        return await merge_tool_configs_into_project_config(db, None, {})

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return await merge_tool_configs_into_project_config(db, None, {})

    config = dict(project.config) if project.config else {}
    merged = await merge_tool_configs_into_project_config(db, project_id, config)
    from ..knowledge.sources.repository_access import registered_repositories

    if registered := await registered_repositories(db, project_id):
        listed = [entry for entry in (merged.get("bitbucket_allowed_repos") or []) if entry]
        merged["bitbucket_allowed_repos"] = [*listed, *registered]
    from ..classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY, classification_tool_policy_section

    # Set last, from the row's own classification: no stored key or tool config can supply it.
    return {
        **apply_runtime_policy_bundle(merged),
        CLASSIFICATION_TOOL_POLICY_KEY: await classification_tool_policy_section(
            db, project.config, project_id=project_id
        ),
    }


async def get_project_config_for_user(project_id: str, user_id: str, db: AsyncSession) -> dict:
    """Get project config, verifying user has access."""
    user_project_ids = await get_user_project_ids(user_id, db)
    if project_id not in user_project_ids:
        return {}
    return await get_project_config(project_id, db)
