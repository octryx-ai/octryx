"""Current human Workspace membership and the work-role holders that decide Workflow nodes."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, Project, ProjectGroup, User, UserGroup, UserProject
from ...models.runtime.work_role_model import WorkRole, WorkRoleAssignment
from ..work_role_model.effective import members_with
from ..work_role_model.seeds import WORK_ROLE_KEYS


async def active_human(db: AsyncSession, user_id: str) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True),
        User.account_type == "human").execution_options(populate_existing=True))).scalar_one_or_none()


async def workspace_humans(db: AsyncSession, project_id: str | None) -> dict[str, User]:
    # Never the admin cross-Workspace shortcut.
    if not project_id:
        return {}
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None or not project.is_active:
        return {}
    direct = select(UserProject.user_id).where(UserProject.project_id == project_id)
    groups = (select(UserGroup.user_id).join(IdentityGroup, IdentityGroup.id == UserGroup.group_id)
              .join(ProjectGroup, ProjectGroup.group_id == IdentityGroup.id)
              .where(ProjectGroup.project_id == project_id, IdentityGroup.is_active.is_(True)))
    users = (await db.execute(select(User).where(User.is_active.is_(True), User.account_type == "human",
        or_(User.id.in_(direct), User.id.in_(groups))).execution_options(populate_existing=True))).scalars().all()
    return {user.id: user for user in users}


async def work_role_members(db: AsyncSession, project_id: str | None, role_key: str) -> tuple[str, ...]:
    if role_key not in WORK_ROLE_KEYS or not project_id:
        return ()
    eligible = await workspace_humans(db, project_id)
    if not eligible:
        return ()
    return await members_with(db, project_id, role_key=role_key, user_ids=eligible)


async def lock_actor_membership(db: AsyncSession, project_id: str | None, user_id: str,
                                 *, role_key: str | None = None) -> None:
    # Re-resolve after locking: a revocation may have won before the lock.
    await db.execute(select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True))
    if not project_id:
        return
    await db.execute(select(Project).where(Project.id == project_id).with_for_update()
                     .execution_options(populate_existing=True))
    await db.execute(select(UserProject).where(UserProject.user_id == user_id,
                                              UserProject.project_id == project_id).with_for_update())
    groups = list((await db.execute(select(UserGroup.group_id).join(ProjectGroup,
        ProjectGroup.group_id == UserGroup.group_id).where(UserGroup.user_id == user_id,
        ProjectGroup.project_id == project_id))).scalars())
    if groups:
        await db.execute(select(IdentityGroup).where(IdentityGroup.id.in_(groups)).with_for_update())
        await db.execute(select(UserGroup).where(UserGroup.user_id == user_id,
                                                UserGroup.group_id.in_(groups)).with_for_update())
        await db.execute(select(ProjectGroup).where(ProjectGroup.project_id == project_id,
                                                   ProjectGroup.group_id.in_(groups)).with_for_update())
    if role_key:
        roles = select(WorkRole.id).where(WorkRole.key == role_key,
                                          or_(WorkRole.project_id.is_(None), WorkRole.project_id == project_id))
        await db.execute(select(WorkRoleAssignment).where(WorkRoleAssignment.project_id == project_id,
            WorkRoleAssignment.role_id.in_(roles)).with_for_update().execution_options(populate_existing=True))
