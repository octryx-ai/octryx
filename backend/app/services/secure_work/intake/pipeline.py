"""The one intake pipeline: list -> map -> upsert -> close, built from the ServiceNow intake.

For every :class:`~.protocol.RecordSource` (ServiceNow, Custom REST):

- **list** (``source.read``): the open records, ``complete`` only when the whole open set was read, plus the
  records closed since the last successful sync where the source can tell (``Listed.changed``);
- **map** (``source.payload``): one record -> a work item payload, deduplicated by ``source_id`` (then
  ``source_key``) within ``(source_type, source_instance)``; a record the source cannot identify is
  ``skipped_invalid``, never imported under a made-up key;
- **guard** (``workspace_immutable.require_no_foreign_source_items``, sync only): before anything is written, a
  record the sync would write that is an item of another Workspace fails the run with the 409
  ``workspace_immutable``; every read below is scoped to the intake's Workspace, so an item of another Workspace is
  never read, closed or counted (it answers like a missing one; a preview reads nothing else);
- **upsert**: creates or updates; a state set by an applied platform transition is never regressed by a sync
  (``_locally_transitioned``: the latest real state event is not the source's own), the item's other
  ``source_fields_json`` entries (e.g. ``platform_notes``) are kept and the source's own live under its type;
- **close**: a listed record in a closed state closes its item (a closed record without an item is not imported),
  so do records closed since the last sync, and, **only when the listing is complete**, items whose record left the
  open set and that the listing covers (``source.in_scope``).

A preview (``dry_run``) counts the same without writing. The summary keeps ServiceNow's keys, so its run history
reads like any ServiceNow run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, User, WorkItem, WorkItemStateEvent, WorkItemSyncConfig, WorkItemSyncRun
from ....time_utils import utc_now
from ..serializers import serialize_sync_run
from ..workspace_immutable import insert_source_item, require_no_foreign_source_items
from .closing import LOOKUP_CHUNK, close_changed, close_item
from .protocol import Listed, RecordSource
from .runs import TRIGGER_MANUAL

PREVIEW_ITEMS = 10
SAMPLE_KEYS = ("source_key", "title", "source_status", "work_state", "source_url", "issue_type")


def text(value: object, limit: int) -> str | None:
    """A stripped, bounded text or ``None``: the column sizes of ``WorkItem`` (title 500, keys 220, status 120)."""
    stripped = str(value).strip() if value not in (None, "") else ""
    return stripped[:limit] or None


async def existing_item(db: AsyncSession, source_type: str, payload: Mapping[str, Any]) -> WorkItem | None:
    """The payload's item in the payload's (the intake's) Workspace."""
    base = select(WorkItem).where(WorkItem.project_id == payload["project_id"], WorkItem.source_type == source_type,
                                  WorkItem.source_instance == payload["source_instance"])
    found = (await db.execute(base.where(WorkItem.source_id == payload["source_id"]))).scalars().first()
    return found or (await db.execute(base.where(WorkItem.source_key == payload["source_key"]))).scalars().first()


async def _existing_closed(db: AsyncSession, source: RecordSource, row: WorkItemSyncConfig, listed: Listed,
                           closed: list[dict[str, Any]]) -> dict[str, WorkItem]:
    """The intake Workspace's items of the listing's closed records, by ``source_id`` and ``source_key``
    (``existing_item``'s lookup), in one query per chunk: a Scripted REST listing carries every closed record."""
    found: dict[str, WorkItem] = {}
    base = select(WorkItem).where(WorkItem.project_id == row.project_id, WorkItem.source_type == source.source_type,
                                  WorkItem.source_instance == listed.instance)
    for start in range(0, len(closed), LOOKUP_CHUNK):
        chunk = closed[start:start + LOOKUP_CHUNK]
        for column, key in ((WorkItem.source_key, "source_key"), (WorkItem.source_id, "source_id")):
            rows = (await db.execute(base.where(column.in_([payload[key] for payload in chunk])))).scalars()
            found.update({getattr(item, key): item for item in rows})
    return found


async def _locally_transitioned(db: AsyncSession, item: WorkItem, source_type: str) -> bool:
    latest = (await db.execute(
        select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id,
                                         WorkItemStateEvent.dry_run.is_(False))
        .order_by(WorkItemStateEvent.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return latest is not None and latest.to_state == item.work_state and latest.source != source_type


async def _upsert(db: AsyncSession, source_type: str, payload: dict[str, Any]) -> str:
    """``imported``, ``updated`` or ``unchanged``; the payload's ``_fields`` go to ``source_fields_json[type]``.
    The run's collision guard has already refused a record that is an item of another Workspace; one inserted there
    since is refused at the insert (``insert_source_item``)."""
    fields = payload.pop("_fields")
    item = await existing_item(db, source_type, payload)
    if item is None:
        created = WorkItem(**payload, source_fields_json={source_type: fields}, imported_at=utc_now(),
                           synced_at=utc_now(), sync_state="imported")
        if (item := await insert_source_item(db, created)) is created:
            return "imported"
    protected = await _locally_transitioned(db, item, source_type)
    changed = False
    for key, value in payload.items():
        if (key == "work_state" and protected) or getattr(item, key) == value:
            continue
        setattr(item, key, value)
        changed = True
    merged = {**dict(item.source_fields_json or {}), source_type: fields}
    if merged != item.source_fields_json:
        item.source_fields_json, changed = merged, True
    item.synced_at, item.sync_state = utc_now(), "updated" if changed else "unchanged"
    return "updated" if changed else "unchanged"


def _sample(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in SAMPLE_KEYS}


async def run_intake(db: AsyncSession, *, source: RecordSource, row: WorkItemSyncConfig, user: User, dry_run: bool,
                     trigger: str = TRIGGER_MANUAL) -> dict[str, Any]:
    """Preview (``dry_run``) or sync the intake; the recorded run. A source's own error type propagates."""
    intake = source.intake_of(row)
    run = WorkItemSyncRun(sync_config_id=row.id, triggered_by=user.id, mode="dry_run" if dry_run else "sync",
                          limit=str(intake["max_items"]), query_preview=source.query_preview(intake))
    db.add(run)
    started = utc_now()  # the next run's watermark: what changed after it is read again
    listed = await source.read(db, row, intake, dry_run=dry_run, user=user)
    mapped = [(record, source.payload(row, listed, group, record, intake)) for group, record in listed.entries]
    opened = [payload for record, payload in mapped if payload is not None and not source.is_closed(record, intake)]
    if not dry_run:
        await require_no_foreign_source_items(
            db, project_id=row.project_id, source_type=source.source_type, source_instance=listed.instance,
            source_ids=[payload["source_id"] for payload in opened],
            source_keys=[payload["source_key"] for payload in opened])
    counts = {"open": 0, "imported": 0, "updated": 0, "unchanged": 0, "closed": 0, "skipped_closed": 0,
              "skipped_invalid": 0, "unmapped_states": 0, **listed.counts}
    seen: set[str] = set()
    samples: list[dict[str, Any]] = []
    known = await _existing_closed(db, source, row, listed, [
        payload for record, payload in mapped if payload is not None and source.is_closed(record, intake)])
    for record, payload in mapped:
        if payload is None:
            counts["skipped_invalid"] += 1
            continue
        seen.add(payload["source_id"])
        if source.is_closed(record, intake):
            existing = known.get(payload["source_id"]) or known.get(payload["source_key"])
            if existing is None:
                counts["skipped_closed"] += 1
            elif dry_run and existing.work_state != "done":
                counts["closed"] += 1
            elif not dry_run:
                reason = f"Closed in {source.label} ({payload['source_status']})"
                counts["closed"] += await close_item(db, existing, user, reason, payload["source_status"],
                                                     source_type=source.source_type)
            continue
        existing = await existing_item(db, source.source_type, payload)
        counts["open"] += 1
        counts["unmapped_states"] += payload["_fields"].get("state_mapping") == "unmapped"
        if len(samples) < PREVIEW_ITEMS:
            samples.append(_sample(payload))
        if dry_run:
            counts["imported" if existing is None else "updated"] += 1
        else:
            counts[await _upsert(db, source.source_type, payload)] += 1
            await db.flush()
    counts["closed_since_last_sync"] = await close_changed(
        db, row=row, instance=listed.instance, changed=listed.changed, seen=seen, user=user, dry_run=dry_run,
        source_type=source.source_type, label=source.label)
    counts["closed"] += counts["closed_since_last_sync"]
    if listed.complete:
        counts["closed"] += await _close_left(db, source, row, listed, seen, user, dry_run=dry_run)
    summary = {**counts, "trigger": trigger, "complete": listed.complete,
               "changed_window_minutes": listed.changed.minutes, "changed_complete": listed.changed.complete,
               **source.summary_extra(listed, intake)}
    run.summary_json, run.sample_items_json = summary, samples
    run.status, run.completed_at = "completed", utc_now()
    if not dry_run:
        row.source_instance, row.last_sync_at, row.last_sync_status = listed.instance, started, "completed"
        row.last_sync_summary_json = summary
        db.add(AuditLog(user_id=user.id, action=source.sync_audit_action, resource_type="work_item_sync_config",
                        resource_id=row.id, details={"project_id": row.project_id, **counts}))
    await db.flush()
    return {"sync_run": serialize_sync_run(run), "summary": summary, "items": samples}


async def _close_left(db: AsyncSession, source: RecordSource, row: WorkItemSyncConfig, listed: Listed,
                      seen: set[str], user: User, *, dry_run: bool) -> int:
    """Items whose record left the open set (listing complete): closed, or counted in a dry run."""
    items = (await db.execute(select(WorkItem).where(
        WorkItem.sync_config_id == row.id, WorkItem.project_id == row.project_id,
        WorkItem.source_type == source.source_type, WorkItem.source_instance == listed.instance,
        WorkItem.work_state != "done",
    ))).scalars().all()
    left = [item for item in items if item.source_id not in seen and source.in_scope(item, listed)]
    if dry_run:
        return len(left)
    reason = f"Left the open set in {source.label}"
    return sum([await close_item(db, item, user, reason, source_type=source.source_type) for item in left])


__all__ = ["PREVIEW_ITEMS", "existing_item", "run_intake", "text"]
