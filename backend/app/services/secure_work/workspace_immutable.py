"""A Work Item and an intake (``WorkItemSyncConfig``) keep the Workspace they were created in."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem

CODE_WORKSPACE_IMMUTABLE = "workspace_immutable"
_LOOKUP_CHUNK = 500


def require_unchanged_workspace(current: str | None, requested: str | None, *, what: str) -> None:
    if (requested or None) != (current or None):
        raise HTTPException(status_code=409, detail={
            "code": CODE_WORKSPACE_IMMUTABLE,
            "message": f"The Workspace of a {what} cannot change after its creation; nothing was changed.",
        })


async def require_no_foreign_source_items(
    db: AsyncSession, *, project_id: str | None, source_type: str, source_instance: str,
    source_ids: Iterable[str | None] = (), source_keys: Iterable[str | None] = (),
) -> None:
    base = select(WorkItem.project_id).where(
        WorkItem.source_type == source_type, WorkItem.source_instance == source_instance,
        WorkItem.project_id.is_distinct_from(project_id))
    for column, values in ((WorkItem.source_id, source_ids), (WorkItem.source_key, source_keys)):
        wanted = sorted({str(value) for value in values if value})
        for start in range(0, len(wanted), _LOOKUP_CHUNK):
            found = (await db.execute(base.where(column.in_(wanted[start:start + _LOOKUP_CHUNK])).limit(1))).first()
            if found is not None:
                require_unchanged_workspace(found.project_id, project_id, what="Work Item")


async def insert_source_item(db: AsyncSession, item: WorkItem) -> WorkItem:
    await db.flush()  # only the insert itself is inside the savepoint
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
        return item
    # A concurrent first import in another Workspace can win the insert after the guard's read
    except IntegrityError:
        winner = (await db.execute(select(WorkItem).where(
            WorkItem.source_type == item.source_type, WorkItem.source_instance == item.source_instance,
            WorkItem.source_key == item.source_key))).scalars().first()
        if winner is None:
            raise
    require_unchanged_workspace(winner.project_id, item.project_id, what="Work Item")
    return winner


__all__ = ["CODE_WORKSPACE_IMMUTABLE", "insert_source_item", "require_no_foreign_source_items",
           "require_unchanged_workspace"]
