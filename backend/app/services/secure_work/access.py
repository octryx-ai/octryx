"""Secure-work access boundary.

Two explicit layers:

- platform role: ``require_work_operator`` gates the HTTP work-management surface; its reads
  (``require_work_reader``) are open to Workspace members too;
- workspace scope: a Work Item belongs to the workspace in ``WorkItem.project_id``. A platform
  admin is cross-workspace; everyone else needs access to that project under the existing
  membership/group policy (``get_user_project_ids``); an item without a project is admin-only.

Object helpers resolve the owning Work Item (for a Change Plan: its ``work_item_id``) and deny
before any service call, so a refused request never reaches a provider, a mutation or an audit
row of the guarded operation. A Work Item of a Workspace outside the caller's scope answers exactly like a missing
record (404 with the addressed record's own wording: the item, or the Change Plan, run or pull request addressed
through it), so an outsider never learns that it exists; a Work Item without a Workspace is 403 (admin-only).
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Role, User, UserRole, WorkChangePlan, WorkItem
from ..project import get_user_project_ids

WORK_OPERATOR_ROLES = {"admin", "operation", "operations", "operator"}
PLATFORM_ADMIN_ROLE = "admin"
CHANGE_PLAN_NOT_FOUND = "Change Plan not found"


async def _platform_role_names(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return {str(row[0] or "").strip().lower() for row in rows.all()}


async def require_work_operator(db: AsyncSession, current_user: User) -> None:
    roles = await _platform_role_names(db, current_user.id)
    if roles & WORK_OPERATOR_ROLES:
        return
    raise HTTPException(status_code=403, detail="Work management requires admin or operation role")


async def require_work_reader(db: AsyncSession, current_user: User) -> None:
    """Read access to Work: a work operator, or a member of at least one Workspace.

    A team leader shows the team its work: members read the Work items, Board, Plans, Epics and
    pull requests of their own Workspaces. Writing and managing stays with ``require_work_operator``. Which
    Workspaces a member reads is still bound by the scope dependency and the lists' ``work_scope_project_ids``.
    """
    roles = await _platform_role_names(db, current_user.id)
    if roles & WORK_OPERATOR_ROLES or await get_user_project_ids(current_user.id, db):
        return
    raise HTTPException(status_code=403, detail="Work is shown to the members of a Workspace; you are not a member "
                                                "of any Workspace yet")


async def work_scope_project_ids(db: AsyncSession, current_user: User) -> set[str] | None:
    """Return the workspaces whose Work Items ``current_user`` may access.

    ``None`` means a verified platform admin (every workspace, including items without one).
    Otherwise the set holds the project ids from direct and group-derived membership; it can be
    empty. Callers filter with ``WorkItem.project_id IN <set>``, which already excludes items
    without a project. This does not check the operator role; callers keep that check explicit.
    """
    if PLATFORM_ADMIN_ROLE in await _platform_role_names(db, current_user.id):
        return None
    return set(await get_user_project_ids(current_user.id, db))


def work_item_in_scope(scope: set[str] | None, item: WorkItem) -> bool:
    """Whether ``item`` lies in ``scope`` as returned by ``work_scope_project_ids``."""
    return scope is None or (bool(item.project_id) and item.project_id in scope)


WORK_ITEM_NOT_FOUND = "Work Item not found"


async def require_work_item_scope(db: AsyncSession, current_user: User, item: WorkItem, *,
                                  missing: str = WORK_ITEM_NOT_FOUND) -> WorkItem:
    """Return ``item`` when ``current_user`` may access its workspace: one outside the caller's Workspaces is the 404
    ``missing`` (the addressed record's answer when it does not exist), one without a Workspace 403."""
    scope = await work_scope_project_ids(db, current_user)
    if scope is None:
        return item
    if not item.project_id:
        raise HTTPException(status_code=403, detail="Work Item has no workspace; only a platform admin can access it")
    if item.project_id not in scope:
        raise HTTPException(status_code=404, detail=missing)
    return item


async def get_scoped_work_item(db: AsyncSession, current_user: User, work_item_id: str, *,
                               missing: str = WORK_ITEM_NOT_FOUND) -> WorkItem:
    """Load a Work Item by id and enforce its workspace scope: 404 ``missing`` when it does not exist or lies outside
    the caller's Workspaces, 403 for an item without a Workspace."""
    item = await db.get(WorkItem, work_item_id) if work_item_id else None
    if item is None:
        raise HTTPException(status_code=404, detail=missing)
    return await require_work_item_scope(db, current_user, item, missing=missing)


async def get_scoped_change_plan(
    db: AsyncSession, current_user: User, change_plan_id: str
) -> tuple[WorkChangePlan, WorkItem]:
    """Load a Change Plan and its owning Work Item, then enforce that item's workspace scope."""
    plan = await db.get(WorkChangePlan, change_plan_id) if change_plan_id else None
    if plan is None:
        raise HTTPException(status_code=404, detail=CHANGE_PLAN_NOT_FOUND)
    item = await get_scoped_work_item(db, current_user, plan.work_item_id, missing=CHANGE_PLAN_NOT_FOUND)
    return plan, item


async def get_visible_change_plan(
    db: AsyncSession, current_user: User, change_plan_id: str
) -> tuple[WorkChangePlan, WorkItem]:
    """Like ``get_scoped_change_plan`` but non-disclosing: out of scope is the same 404 as missing.

    For surfaces addressed by guessable references (MCP), where a 403 would confirm that a
    foreign plan exists.
    """
    plan = await db.get(WorkChangePlan, change_plan_id) if change_plan_id else None
    item = await db.get(WorkItem, plan.work_item_id) if plan is not None else None
    if item is None or not work_item_in_scope(await work_scope_project_ids(db, current_user), item):
        raise HTTPException(status_code=404, detail=CHANGE_PLAN_NOT_FOUND)
    return plan, item
