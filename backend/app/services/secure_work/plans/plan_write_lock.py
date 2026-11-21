"""Per-Work-Item write serialization for Change Plans.

Every writer that allocates a plan version or changes a plan status (deterministic and LLM
generation, clarification answers, decisions) takes the same lock first: the owning ``WorkItem``
row, ``SELECT ... FOR UPDATE``. Writers of one Work Item therefore run one after another, and the
state each one validates is the state it writes on. The lock is taken immediately before the
writes, never across a model call.

After the lock, callers re-read what they validate with :func:`reread_plan`, which bypasses the
session's identity map, so an object loaded before the lock cannot hide a change committed in the
meantime.

SQLite ignores ``FOR UPDATE``; tests on SQLite prove the re-read and comparison logic, not the
PostgreSQL row lock itself.
"""

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
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_work_item_for_plan_write(db: AsyncSession, work_item_id: str) -> WorkItem:
    """Lock the Work Item row that owns the plans about to be written; 404 when it is gone."""
    item = (await db.execute(work_item_lock_statement(work_item_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return item


async def reread_plan(db: AsyncSession, change_plan_id: str) -> WorkChangePlan | None:
    """The plan as stored now, overwriting any stale copy in the session."""
    return (
        await db.execute(
            select(WorkChangePlan)
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
    """Whether ``exc`` is the known (work_item_id, version) uniqueness race and nothing else.

    PostgreSQL names the constraint; SQLite names the columns.
    """
    text = str(getattr(exc, "orig", None) or exc)
    return PLAN_VERSION_CONSTRAINT in text or "work_change_plans.work_item_id, work_change_plans.version" in text
