"""Successive runs on one Work item: at most one active run per item and workflow, and the earlier runs a new run may
adopt from ("Lifecycle of successive runs")."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.secure_work import WorkItem
from .records import WorkflowRunError
from .states import ACTIVE_STATUSES


async def require_no_active_run(db: AsyncSession, item: WorkItem | None, workflow_key: str) -> None:
    if item is None:
        return
    # Serialises concurrent starts on the same item (a no-op on SQLite).
    await db.execute(select(WorkItem.id).where(WorkItem.id == item.id).with_for_update())
    active = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id == item.id, WorkflowRun.workflow_key == workflow_key,
        WorkflowRun.parent_run_id.is_(None), WorkflowRun.status.in_(tuple(ACTIVE_STATUSES)),
    ))).scalars().first()
    if active is not None:
        raise WorkflowRunError(
            "run_already_active",
            f"Run {active.id} of '{workflow_key}' is still {active.status} on this Work item; continue or abort it "
            "before starting another.", 409)


async def earlier_runs(db: AsyncSession, run: WorkflowRun, *, same_repository: bool = True) -> list[WorkflowRun]:
    if not run.work_item_id:
        return []
    query = select(WorkflowRun).where(WorkflowRun.work_item_id == run.work_item_id, WorkflowRun.id != run.id)
    if same_repository:
        query = query.where(WorkflowRun.repository == run.repository)
    rows = (await db.execute(query.order_by(WorkflowRun.created_at.desc()))).scalars().all()
    return [row for row in rows if row.status not in ACTIVE_STATUSES]


__all__ = ["earlier_runs", "require_no_active_run"]
