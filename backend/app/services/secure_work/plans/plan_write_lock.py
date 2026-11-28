"""Per-Work-Item write serialization for Change Plans."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkChangePlan, WorkItem

PLAN_VERSION_CONSTRAINT = "uq_work_change_plans_item_version"


def work_item_lock_statement(work_item_id: str):
    return (
        select(WorkItem)
        .where(WorkItem.id == work_item_id)
        # Plan writers that take this row lock run one after another, and each writes on the state it validated.
        # SQLite ignores FOR UPDATE; tests there prove the re-read, not the lock.
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_work_item_for_plan_write(db: AsyncSession, work_item_id: str) -> WorkItem:
    item = (await db.execute(work_item_lock_statement(work_item_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return item


async def reread_plan(db: AsyncSession, change_plan_id: str) -> WorkChangePlan | None:
    return (
        await db.execute(
            select(WorkChangePlan)
            # Past the identity map: an object loaded before the lock cannot hide a change committed meanwhile
            .where(WorkChangePlan.id == change_plan_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def latest_plan_version(db: AsyncSession, work_item_id: str) -> int:
    value = (
        await db.execute(select(func.max(WorkChangePlan.version)).where(WorkChangePlan.work_item_id == work_item_id))
    ).scalar_one_or_none()
    return int(value or 0)


def is_plan_version_conflict(exc: IntegrityError) -> bool:
    # Only the (work_item_id, version) uniqueness race: PostgreSQL names the constraint, SQLite the columns.
    text = str(getattr(exc, "orig", None) or exc)
    return PLAN_VERSION_CONSTRAINT in text or "work_change_plans.work_item_id, work_change_plans.version" in text
