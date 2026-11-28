"""The platform role and the Workspace scope that guard Secure Work."""

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
    """Read access to Work: a work operator, or a member of at least one Workspace."""
    roles = await _platform_role_names(db, current_user.id)
    if roles & WORK_OPERATOR_ROLES or await get_user_project_ids(current_user.id, db):
        return
    raise HTTPException(status_code=403, detail="Work is shown to the members of a Workspace; you are not a member "
                                                "of any Workspace yet")


async def work_scope_project_ids(db: AsyncSession, current_user: User) -> set[str] | None:
    if PLATFORM_ADMIN_ROLE in await _platform_role_names(db, current_user.id):
        # A platform admin: every Workspace, also items without one
        return None
    return set(await get_user_project_ids(current_user.id, db))


def work_item_in_scope(scope: set[str] | None, item: WorkItem) -> bool:
    return scope is None or (bool(item.project_id) and item.project_id in scope)


WORK_ITEM_NOT_FOUND = "Work Item not found"


async def require_work_item_scope(db: AsyncSession, current_user: User, item: WorkItem, *,
                                  missing: str = WORK_ITEM_NOT_FOUND) -> WorkItem:
    scope = await work_scope_project_ids(db, current_user)
    if scope is None:
        return item
    if not item.project_id:
        raise HTTPException(status_code=403, detail="Work Item has no workspace; only a platform admin can access it")
    if item.project_id not in scope:
        # The addressed record's own not-found answer, so an outsider never learns that the item exists
        raise HTTPException(status_code=404, detail=missing)
    return item


async def get_scoped_work_item(db: AsyncSession, current_user: User, work_item_id: str, *,
                               missing: str = WORK_ITEM_NOT_FOUND) -> WorkItem:
    item = await db.get(WorkItem, work_item_id) if work_item_id else None
    if item is None:
        raise HTTPException(status_code=404, detail=missing)
    return await require_work_item_scope(db, current_user, item, missing=missing)


async def get_scoped_change_plan(
    db: AsyncSession, current_user: User, change_plan_id: str
) -> tuple[WorkChangePlan, WorkItem]:
    plan = await db.get(WorkChangePlan, change_plan_id) if change_plan_id else None
    if plan is None:
        raise HTTPException(status_code=404, detail=CHANGE_PLAN_NOT_FOUND)
    item = await get_scoped_work_item(db, current_user, plan.work_item_id, missing=CHANGE_PLAN_NOT_FOUND)
    return plan, item


async def get_visible_change_plan(
    db: AsyncSession, current_user: User, change_plan_id: str
) -> tuple[WorkChangePlan, WorkItem]:
    plan = await db.get(WorkChangePlan, change_plan_id) if change_plan_id else None
    item = await db.get(WorkItem, plan.work_item_id) if plan is not None else None
    # Out of scope is the same 404: a 403 would confirm to a guessable (MCP) reference that a foreign plan exists
    if item is None or not work_item_in_scope(await work_scope_project_ids(db, current_user), item):
        raise HTTPException(status_code=404, detail=CHANGE_PLAN_NOT_FOUND)
    return plan, item
