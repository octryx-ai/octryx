"""Persist synced Jira issues as Work items: who wins the state, and what fell out of the filter.

- **Local lifecycle protection:** a state set by an applied workflow transition is never regressed by the
  sync; the platform lifecycle can be ahead of Jira (e.g. ``review`` when the Jira workflow has none).
- **A terminal state at the source always wins:** when Jira reports the issue finished (its statusCategory
  is ``done``, or the explicit status mapping puts it into a terminal Work state), the item closes even
  against a locally transitioned state. The state event (``source: jira_sync``) says why.
- **Fell out of the filter:** an item the intake imported that a *complete* sync result no longer contains
  is marked ``sync_state: removed_from_source_filter`` and closed (``done``), with a state event. Only a
  complete result may conclude this: a limited, paged-off or request-supplied result never does (see
  :func:`fall_out_check`).

State events written by the sync itself never count as a local transition, so an issue that comes back
into the filter (or is reopened in Jira) takes its source state again.

- **An unchanged item is not written:** when every normalized field equals the stored row and the row already
  says ``sync_state: unchanged``, the run leaves the row alone (no ``synced_at``, no ``updated_at``); otherwise
  every item would be rewritten on every run. ``synced_at`` is therefore when the sync last
  changed the item; when the intake last ran is the config's ``last_sync_at``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkItem, WorkItemStateEvent, WorkItemSyncConfig
from ....time_utils import utc_now
from ..workspace_immutable import insert_source_item, require_unchanged_workspace

SYNC_EVENT_SOURCE = "jira_sync"
TERMINAL_STATES = frozenset({"done", "rejected"})
CLOSED_STATE = "done"
SYNC_STATE_REMOVED = "removed_from_source_filter"
REASON_CLOSED_AT_SOURCE = "closed_at_source"
FALL_OUT_APPLY = "apply"
FALL_OUT_DISABLED = "disabled_by_request"
FALL_OUT_NOT_AUTHORITATIVE = "request_payload_not_authoritative"
FALL_OUT_INCOMPLETE = "source_result_incomplete"


def fall_out_check(
    payload: dict[str, Any], *, source: dict[str, Any], limit: int | None, matched_count: int
) -> str:
    """``apply`` when this run may conclude that an absent item fell out of the filter, else why not.

    A connector result does so by default (``mark_removed_from_filter: false`` turns it off); issues
    supplied in the request only with an explicit ``mark_removed_from_filter: true``. Either way the
    result must be complete: every page fetched and nothing cut off by the run's limit.
    """
    requested = payload.get("mark_removed_from_filter")
    if requested is False:
        return FALL_OUT_DISABLED
    from_request = dict(source.get("metadata") or {}).get("source") == "request_payload"
    if from_request and requested is not True:
        return FALL_OUT_NOT_AUTHORITATIVE
    if not source.get("source_complete") or (limit is not None and matched_count > limit):
        return FALL_OUT_INCOMPLETE
    return FALL_OUT_APPLY


def source_terminal_state(payload: dict[str, Any]) -> str | None:
    """The terminal Work state the source reports for this issue, ``None`` while it is still open."""
    mapped = str(payload.get("work_state") or "")
    if mapped in TERMINAL_STATES:
        return mapped
    fields = payload.get("source_fields_json") if isinstance(payload.get("source_fields_json"), dict) else {}
    mapping = fields.get("status_mapping") if isinstance(fields.get("status_mapping"), dict) else {}
    return CLOSED_STATE if mapping.get("category") == "done" else None


async def work_state_is_locally_transitioned(db: AsyncSession, item: WorkItem) -> bool:
    """True when the item's current work_state came from an applied transition (not from the sync itself)."""
    latest = (
        await db.execute(
            select(WorkItemStateEvent)
            .where(
                WorkItemStateEvent.work_item_id == item.id,
                WorkItemStateEvent.dry_run.is_(False),
                WorkItemStateEvent.source != SYNC_EVENT_SOURCE,
            )
            .order_by(WorkItemStateEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return latest is not None and str(latest.to_state or "") == str(item.work_state or "")


def _sync_event(
    item: WorkItem, *, to_state: str, actor_id: str, reason: str, detail: dict[str, Any]
) -> WorkItemStateEvent:
    return WorkItemStateEvent(
        work_item_id=item.id,
        from_state=item.work_state,
        to_state=to_state,
        actor_id=actor_id,
        reason=reason,
        source=SYNC_EVENT_SOURCE,
        dry_run=False,
        jira_sync_preview_json={"mode": "source_state", "will_mutate_jira": False, **detail},
        conflict_json={},
    )


#: Keys per ``IN`` list when the run loads its existing items (well inside every driver's parameter limit).
_PREFETCH_CHUNK = 500


async def existing_items_by_key(
    db: AsyncSession, *, project_id: str | None, source_type: str, source_instance: str, source_keys: Iterable[str]
) -> dict[str, WorkItem]:
    """The intake Workspace's stored items of these issue keys in one query per chunk, instead of one per issue."""
    keys = sorted({str(key) for key in source_keys if key})
    found: dict[str, WorkItem] = {}
    for start in range(0, len(keys), _PREFETCH_CHUNK):
        rows = (await db.execute(select(WorkItem).where(
            WorkItem.project_id == project_id,
            WorkItem.source_type == source_type,
            WorkItem.source_instance == source_instance,
            WorkItem.source_key.in_(keys[start:start + _PREFETCH_CHUNK]),
        ))).scalars()
        found.update({row.source_key: row for row in rows})
    return found


async def upsert_jira_work_item(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    actor_id: str,
    known_items: dict[str, WorkItem] | None = None,
) -> tuple[str, bool]:
    """Insert or update one issue: ``(imported|updated|unchanged, closed_at_source)``.

    ``known_items`` are the run's prefetched items by issue key (:func:`existing_items_by_key`); an issue key
    absent from them is new (and is added to them). Without them the item is looked up on its own.
    """
    if known_items is not None:
        existing = known_items.get(payload["source_key"])
    else:
        existing = (
            await db.execute(
                select(WorkItem).where(
                    WorkItem.source_type == payload["source_type"],
                    WorkItem.source_instance == payload["source_instance"],
                    WorkItem.source_key == payload["source_key"],
                )
            )
        ).scalar_one_or_none()
    now = utc_now()
    if existing is None:
        created = WorkItem(**payload, imported_at=now, synced_at=now, sync_state="imported")
        existing = await insert_source_item(db, created)  # another sync's insert since the lookup: its row
        if known_items is not None:
            known_items[payload["source_key"]] = existing
        if existing is created:
            return "imported", False
    if "project_id" in payload:  # a state-only update names no Workspace and cannot move the item
        require_unchanged_workspace(existing.project_id, payload["project_id"], what="Work Item")
    terminal = source_terminal_state(payload)
    closed_at_source = terminal is not None and str(existing.work_state or "") not in TERMINAL_STATES
    # Whether the lifecycle is ahead of Jira matters only when the source state would move the item; an
    # unchanged state skips the event lookup (one query per issue and run before).
    state_moves = "work_state" in payload and str(payload.get("work_state") or "") != str(existing.work_state or "")
    protected = await work_state_is_locally_transitioned(db, existing) if (closed_at_source or state_moves) else False
    if closed_at_source:
        status_mapping = dict(dict(payload.get("source_fields_json") or {}).get("status_mapping") or {})
        db.add(_sync_event(
            existing, to_state=terminal, actor_id=actor_id,
            reason=f"{REASON_CLOSED_AT_SOURCE}: Jira reports '{payload.get('source_status')}' as finished",
            detail={"reason": REASON_CLOSED_AT_SOURCE, "source_status": payload.get("source_status"),
                    "status_category": status_mapping.get("category"),
                    "overrode_local_transition": protected},
        ))
        existing.work_state = terminal
    changed = closed_at_source
    for key, value in payload.items():
        if key == "work_state" and (protected or closed_at_source):
            # The lifecycle is ahead of Jira (protected), or the source's terminal state was applied above.
            continue
        if getattr(existing, key) != value:
            setattr(existing, key, value)
            changed = True
    state = "updated" if changed else "unchanged"
    if not changed and existing.sync_state == state:
        return state, False  # nothing to write: the row already says what this run found
    existing.synced_at = now
    existing.sync_state = state
    await db.flush()
    return state, closed_at_source


async def _intake_items(db: AsyncSession, config: WorkItemSyncConfig) -> list[WorkItem]:
    return list((
        await db.execute(
            select(WorkItem).where(
                WorkItem.sync_config_id == config.id,
                WorkItem.project_id == config.project_id,
                WorkItem.source_type == "jira",
                WorkItem.source_instance == config.source_instance,
            )
        )
    ).scalars())


async def preview_removed_from_filter(db: AsyncSession, config: WorkItemSyncConfig, seen_keys: set[str]) -> list[str]:
    """Dry-run counterpart of :func:`close_removed_from_filter`: the keys a real run would close."""
    return sorted(
        row.source_key for row in await _intake_items(db, config)
        if row.source_key not in seen_keys and row.sync_state != SYNC_STATE_REMOVED
    )


async def close_removed_from_filter(
    db: AsyncSession, config: WorkItemSyncConfig, seen_keys: set[str], *, actor_id: str, sync_run_id: str | None
) -> int:
    """Mark and close the intake's items a complete sync no longer returned; the count newly removed."""
    count = 0
    for row in await _intake_items(db, config):
        if row.source_key in seen_keys or row.sync_state == SYNC_STATE_REMOVED:
            continue
        if str(row.work_state or "") not in TERMINAL_STATES:
            db.add(_sync_event(
                row, to_state=CLOSED_STATE, actor_id=actor_id,
                reason=f"{SYNC_STATE_REMOVED}: no longer returned by the intake's Jira filter (complete sync)",
                detail={"reason": SYNC_STATE_REMOVED, "sync_config_id": config.id, "sync_run_id": sync_run_id},
            ))
            row.work_state = CLOSED_STATE
        row.sync_state = SYNC_STATE_REMOVED
        row.synced_at = utc_now()
        count += 1
    await db.flush()
    return count


__all__ = [
    "FALL_OUT_APPLY",
    "SYNC_EVENT_SOURCE",
    "SYNC_STATE_REMOVED",
    "TERMINAL_STATES",
    "close_removed_from_filter",
    "existing_items_by_key",
    "fall_out_check",
    "work_state_is_locally_transitioned",
    "preview_removed_from_filter",
    "source_terminal_state",
    "upsert_jira_work_item",
]
