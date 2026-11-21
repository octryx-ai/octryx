"""Closing work items because their record closed at the source, for every pipeline source.

One owner, so a Custom REST intake closes items exactly like the ServiceNow one: a state event with the source as its
``source`` (``_locally_transitioned`` tells such an event from a person's transition), ``sync_state``
``closed_at_source``, and the record's status kept as ``source_status``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkItem, WorkItemStateEvent, WorkItemSyncConfig
from ....time_utils import utc_now
from .protocol import Changed

LOOKUP_CHUNK = 500


async def close_item(db: AsyncSession, item: WorkItem, user: User, reason: str, status: str | None = None, *,
                     source_type: str) -> bool:
    """Move ``item`` to ``done`` with a state event (``False`` when it already is); ``status`` is the record's
    state at the source, kept as ``source_status`` either way."""
    if status:
        item.source_status = status[:120]
    if item.work_state == "done":
        return False
    db.add(WorkItemStateEvent(work_item_id=item.id, from_state=item.work_state, to_state="done", actor_id=user.id,
                              reason=reason, source=source_type))
    item.work_state, item.sync_state, item.synced_at = "done", "closed_at_source", utc_now()
    return True


async def close_changed(db: AsyncSession, *, row: WorkItemSyncConfig, instance: str, changed: Changed,
                        seen: set[str], user: User, dry_run: bool, source_type: str, label: str) -> int:
    """Close this intake's items (in its Workspace) whose record closed since the last sync and was not in the open
    listing (``seen``); in a dry run, count them."""
    wanted = [source_id for source_id in changed.closed if source_id not in seen]
    closed = 0
    for start in range(0, len(wanted), LOOKUP_CHUNK):
        items = (await db.execute(select(WorkItem).where(
            WorkItem.sync_config_id == row.id, WorkItem.project_id == row.project_id,
            WorkItem.source_type == source_type,
            WorkItem.source_instance == instance, WorkItem.source_id.in_(wanted[start:start + LOOKUP_CHUNK]),
        ))).scalars().all()
        for item in items:
            state = str(changed.closed[item.source_id].get("state") or "").strip()
            if dry_run:
                closed += item.work_state != "done"
            else:
                closed += await close_item(db, item, user, f"Closed in {label} ({state})", state or None,
                                           source_type=source_type)
    return closed


__all__ = ["LOOKUP_CHUNK", "close_changed", "close_item"]
