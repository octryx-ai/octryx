"""A Workspace's roles page: the switch, the assignments and who would lose access.

everything sits behind the per-Workspace switch "role-based tools", OFF by default; a Workspace without
work-role assignments would lock its members out when it is turned on. So the page lists the members without a
role next to the switch; turning it on is the admin's decision, never refused for that reason.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, IdentityProvider, Project, ProjectGroup, User
from ...models.runtime.work_role_model import (
    ANY_PROVIDER,
    SUBJECT_KINDS,
    WorkRole,
    WorkRoleAssignment,
    WorkspaceWorkRoleSettings,
)
from ...time_utils import utc_now
from . import audit
from .admin_catalog import list_roles
from .catalog_scope import CallerScope, connection_names, function_names
from .effective import assignment_matches, effective_permission, held_roles_by_user, subject_facts
from .errors import WorkRoleError, may_admin_workspace, require_workspace_admin, version_conflict
from .grant_checks import grant_view


async def _project(db: AsyncSession, workspace_id: str) -> Project:
    project = await db.get(Project, workspace_id)
    if project is None or not project.is_active:
        raise WorkRoleError("workspace_not_found", "Workspace not found.", 404)
    return project


async def _members(db: AsyncSession, workspace_id: str) -> dict[str, User]:
    from ..workflow_runs.work_roles import workspace_humans

    return await workspace_humans(db, workspace_id)


def _label(user: User | None) -> str:
    return (user.display_name or user.username) if user else ""


def settings_view(row: WorkspaceWorkRoleSettings | None) -> dict[str, Any]:
    if row is None:
        return {"role_based_tools": False, "version": 1, "updated_by": None, "updated_at": None}
    return {"role_based_tools": bool(row.role_based_tools), "version": row.version, "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def _subject_label(db: AsyncSession, row: WorkRoleAssignment) -> str:
    if row.subject_kind == "user":
        return _label(await db.get(User, row.user_id))
    if row.subject_kind == "group":
        group = await db.get(IdentityGroup, row.group_id)
        return group.name if group else ""
    return str(row.claim_value or "")


async def assignment_view(db: AsyncSession, row: WorkRoleAssignment, role: WorkRole | None,
                          member_facts: dict | None = None) -> dict[str, Any]:
    subject: dict[str, Any] = {"kind": row.subject_kind, "label": await _subject_label(db, row)}
    if row.subject_kind == "user":
        subject["user_id"] = row.user_id
    elif row.subject_kind == "group":
        subject["group_id"] = row.group_id
    else:
        subject.update(value=row.claim_value, provider_id=row.provider_id)
    members = sum(1 for facts in (member_facts or {}).values() if assignment_matches(row, facts))
    return {"id": row.id, "workspace_id": row.project_id, "role_id": row.role_id,
            "role_key": role.key if role else None, "role_name": role.name if role else None, "subject": subject,
            "members": members, "is_active": bool(row.is_active), "version": row.version,
            "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def workspace_page(db: AsyncSession, user: User, workspace_id: str) -> dict[str, Any]:
    await _project(db, workspace_id)
    await require_workspace_admin(db, user, workspace_id, "this Workspace's roles")
    members = await _members(db, workspace_id)
    facts = await subject_facts(db, members)
    rows = (await db.execute(select(WorkRoleAssignment).where(WorkRoleAssignment.project_id == workspace_id)
                             .order_by(WorkRoleAssignment.created_at))).scalars().all()
    roles = {row.id: row for row in (await db.execute(select(WorkRole))).scalars().all()}
    held = await held_roles_by_user(db, workspace_id, members)
    from ..admin.governance.admin_access_service import is_global_admin

    without = [{"user_id": uid, "label": _label(member)} for uid, member in sorted(members.items())
               if not held.get(uid) and not await is_global_admin(db, uid)]
    return {"workspace_id": workspace_id,
            "settings": settings_view(await db.get(WorkspaceWorkRoleSettings, workspace_id)),
            "roles": await list_roles(db, user, workspace_id),
            "assignments": [await assignment_view(db, row, roles.get(row.role_id), facts) for row in rows],
            "members_without_role": without, "can_edit": True}


async def set_switch(db: AsyncSession, user: User, workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    await _project(db, workspace_id)
    await require_workspace_admin(db, user, workspace_id, "the switch 'Role-based tools'")
    value = body.get("role_based_tools")
    if not isinstance(value, bool):
        raise WorkRoleError("invalid_switch", "role_based_tools is true or false.", 422)
    row = await db.get(WorkspaceWorkRoleSettings, workspace_id, populate_existing=True)
    current = row.version if row is not None else 1
    if body.get("expected_version") != current:
        raise version_conflict("Workspace role settings")
    before = settings_view(row)
    if row is None:
        row = WorkspaceWorkRoleSettings(project_id=workspace_id, role_based_tools=False, version=1)
        db.add(row)
    if bool(row.role_based_tools) != value or row.updated_at is None:
        row.role_based_tools = value
        row.version = current + 1
        row.updated_by, row.updated_at = user.id, utc_now()
        audit.record(db, actor_id=user.id, action="settings.role_based_tools_changed", target_type="workspace",
                     target_id=workspace_id, label="Role-based tools", workspace_id=workspace_id,
                     before={"role_based_tools": before["role_based_tools"]}, after={"role_based_tools": value})
    await db.flush()
    return settings_view(row)


async def _subject(db: AsyncSession, workspace_id: str, raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("kind") not in SUBJECT_KINDS:
        raise WorkRoleError("invalid_subject", "subject.kind is user, group, sso_group or sso_role.", 422)
    kind = raw["kind"]
    if kind == "user":
        user_id = str(raw.get("user_id") or "")
        if user_id not in await _members(db, workspace_id):
            raise WorkRoleError("not_a_member", "The person must be an active human member of this Workspace.", 409)
        return {"subject_kind": kind, "user_id": user_id, "subject_key": user_id}
    if kind == "group":
        group_id = str(raw.get("group_id") or "")
        bound = (await db.execute(select(IdentityGroup.id).join(ProjectGroup, ProjectGroup.group_id ==
                 IdentityGroup.id).where(IdentityGroup.id == group_id, IdentityGroup.is_active.is_(True),
                                         ProjectGroup.project_id == workspace_id))).scalar_one_or_none()
        if bound is None:
            raise WorkRoleError("group_not_bound", "The group must be active and bound to this Workspace.", 409)
        return {"subject_kind": kind, "group_id": group_id, "subject_key": group_id}
    value = str(raw.get("value") or "").strip()
    if not value or len(value) > 255:
        raise WorkRoleError("invalid_subject", "An SSO group or role needs its claim value (1-255 characters).", 422)
    provider_id = raw.get("provider_id") or None
    if provider_id is not None and await db.get(IdentityProvider, provider_id) is None:
        raise WorkRoleError("unknown_provider", "Unknown identity provider.", 422)
    return {"subject_kind": kind, "claim_value": value, "provider_id": provider_id, "subject_key": value,
            "provider_key": provider_id or ANY_PROVIDER}


async def create_assignment(db: AsyncSession, user: User, workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    await _project(db, workspace_id)
    await require_workspace_admin(db, user, workspace_id, "role assignments")
    role = await db.get(WorkRole, str(body.get("role_id") or ""))
    if role is None or role.project_id not in (None, workspace_id):
        raise WorkRoleError("role_not_found", "The role does not exist in this Workspace.", 404)
    row = WorkRoleAssignment(project_id=workspace_id, role_id=role.id, created_by=user.id, updated_by=user.id,
                             **await _subject(db, workspace_id, body.get("subject")))
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise WorkRoleError("assignment_exists", "This assignment exists; activate it instead.", 409) from None
    view = await assignment_view(db, row, role)
    audit.record(db, actor_id=user.id, action="assignment.created", target_type="assignment", target_id=row.id,
                 label=f"{role.name} · {view['subject']['label']}", workspace_id=workspace_id, after=view)
    await db.flush()
    return view


async def set_assignment_active(db: AsyncSession, user: User, workspace_id: str, assignment_id: str,
                                body: dict[str, Any]) -> dict[str, Any]:
    await require_workspace_admin(db, user, workspace_id, "role assignments")
    row = await db.get(WorkRoleAssignment, assignment_id, populate_existing=True)
    if row is None or row.project_id != workspace_id:
        raise WorkRoleError("assignment_not_found", "Assignment not found.", 404)
    active = body.get("is_active")
    if not isinstance(active, bool):
        raise WorkRoleError("invalid_active", "is_active is true or false.", 422)
    if body.get("expected_version") != row.version:
        raise version_conflict("assignment")
    role = await db.get(WorkRole, row.role_id)
    if bool(row.is_active) != active:
        before = bool(row.is_active)
        row.is_active = active
        row.version += 1
        row.updated_by, row.updated_at = user.id, utc_now()
        audit.record(db, actor_id=user.id, action="assignment.activated" if active else "assignment.revoked",
                     target_type="assignment", target_id=row.id,
                     label=f"{role.name if role else ''} · {await _subject_label(db, row)}",
                     workspace_id=workspace_id, before={"is_active": before}, after={"is_active": active})
        await db.flush()
    return await assignment_view(db, row, role)


async def effective_view(db: AsyncSession, user: User, workspace_id: str, user_id: str | None) -> dict[str, Any]:
    """``/me`` (``user_id`` None) for every member; another person's preview for admins only."""
    from ..access_control import get_project_role_for_user

    await _project(db, workspace_id)
    target = user_id or user.id
    if target != user.id:
        if not await may_admin_workspace(db, user, workspace_id):
            raise WorkRoleError("forbidden", "Only a Workspace admin previews another person's permission.", 403)
    elif await get_project_role_for_user(db, user.id, workspace_id) is None:
        raise WorkRoleError("forbidden", "You are not a member of this Workspace.", 403)
    from .tool_catalog import catalog_tool_names

    grant = await effective_permission(db, target, workspace_id)
    ids = sorted(grant.write_connections or ())
    return grant_view(grant, catalog_tool_names(), function_names=await function_names(db, workspace_id),
                      connection_names=await connection_names(db, CallerScope(db, user), ids, workspace_id))


__all__ = ["create_assignment", "effective_view", "set_assignment_active", "set_switch", "settings_view",
           "workspace_page"]
