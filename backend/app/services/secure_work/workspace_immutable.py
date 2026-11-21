"""A Work Item and an intake (``WorkItemSyncConfig``) keep the Workspace they were created in.

Every write path that could carry another Workspace (Jira and generic intake sync updates of an existing item, an
intake draft saved with a ``project_id``) checks it here before it writes anything: a different Workspace is a 409
``workspace_immutable``. Nothing moves between Workspaces, so whatever is stored for an item or intake (its pull
request records, references, runs) stays in the Workspace it was written for.

An intake sync (Jira, ServiceNow, Custom REST) checks once, before it writes anything, that no record it would write
is already an item of another Workspace (:func:`require_no_foreign_source_items`): the source identity is unique across
Workspaces, so such a record can neither be imported here nor touched there. A preview (dry run) writes nothing and
never asks: every read of a preview, like every other read of a sync (closed records, records closed since the last
sync, items that left the filter), is scoped to the intake's Workspace, so an item of another Workspace answers like
a missing one.

That check reads before the run writes, so a concurrent first import of the same source key in another Workspace can
still win the insert: every intake insert goes through :func:`insert_source_item`, which resolves the source-key
uniqueness conflict at the insert itself (the insert is rolled back, the winning row is read; another Workspace's is
the same 409, the same Workspace's is updated like any existing item).
"""

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
    """The intake sync's one collision guard, before any write (never in a preview): a record it would write (by
    ``source_id`` or ``source_key`` within ``(source_type, source_instance)``) that is an item of another Workspace is
    the 409."""
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
    """``item`` inserted, or the row that won the source key (``uq_work_items_source_key``) since the caller looked:
    the insert runs in a savepoint and is rolled back on that conflict; a winner in another Workspace is the 409
    ``workspace_immutable``, one in ``item``'s Workspace is returned for the caller's update path."""
    await db.flush()  # only the insert itself is inside the savepoint
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
        return item
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
