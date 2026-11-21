"""Jira sync run records: the run row, its summary, the persisted items, and a completed, skipped or blocked run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkItem,
    WorkItemSyncConfig,
    WorkItemSyncRun,
)
from ....time_utils import utc_now
from ..intake.runs import trigger_of
from ..serializers import serialize_sync_run
from ..workspace_immutable import require_no_foreign_source_items
from .jira_item_upsert import (
    FALL_OUT_APPLY,
    close_removed_from_filter,
    existing_items_by_key,
    upsert_jira_work_item,
)
from .jira_mapping import item_preview


def _create_sync_run(
    *,
    config: WorkItemSyncConfig,
    current_user: User,
    limit: int | None,
    query_preview: str,
    dry_run: bool,
) -> WorkItemSyncRun:
    return WorkItemSyncRun(
        sync_config_id=config.id,
        triggered_by=current_user.id,
        mode="dry_run" if dry_run else "sync",
        status="running",
        limit=str(limit) if limit is not None else None,
        query_preview=query_preview,
    )


def _build_summary(
    *,
    query_preview: str,
    source_count: int,
    filtered_count: int,
    valid_count: int,
    dry_run: bool,
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query_preview": query_preview,
        "total_source": source_count,
        "total_after_filter": filtered_count,
        "total_valid": valid_count,
        "imported": 0,
        "updated": 0,
        "unchanged": 0,
        "removed_from_source_filter": 0,
        "skipped": 0,
        "dry_run": dry_run,
        "source": dict(source.get("metadata") or {}),
        "source_complete": bool(source.get("source_complete")),
    }


def _build_blocked_summary(
    *,
    query_preview: str,
    dry_run: bool,
    source: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(source.get("metadata") or {})
    return {
        "query_preview": query_preview,
        "total_source": 0,
        "total_after_filter": 0,
        "total_valid": 0,
        "imported": 0,
        "updated": 0,
        "unchanged": 0,
        "removed_from_source_filter": 0,
        "skipped": 0,
        "dry_run": dry_run,
        "blocked": True,
        "block_reason": metadata.get("reason") or "Jira connector is not configured.",
        "source": metadata,
        "source_complete": True,
    }


def _complete_run(run: WorkItemSyncRun, *, summary: dict[str, Any], normalized: list[dict[str, Any]]) -> None:
    run.status = "completed"
    run.summary_json = summary
    run.sample_items_json = [item_preview(item) for item in normalized[:10]]
    run.completed_at = utc_now()


def _block_run(run: WorkItemSyncRun, *, config: WorkItemSyncConfig, summary: dict[str, Any]) -> None:
    run.status = "blocked"
    run.summary_json = summary
    run.sample_items_json = []
    run.completed_at = utc_now()
    config.last_sync_at = utc_now()
    config.last_sync_status = "blocked"
    config.last_sync_summary_json = summary


async def _persist_sync_items(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    current_user: User,
    normalized: list[dict[str, Any]],
    summary: dict[str, Any],
    fall_out: str,
    seen_keys: set[str],
    sync_run_id: str | None,
) -> None:
    closed_at_source = 0
    # One read for the run's existing items; an unchanged item is then neither re-read nor written.
    known_items = await existing_items_by_key(
        db, project_id=config.project_id, source_type="jira", source_instance=config.source_instance,
        source_keys=(item["source_key"] for item in normalized),
    )
    for item_payload in normalized:
        state, closed = await upsert_jira_work_item(
            db, item_payload, actor_id=current_user.id, known_items=known_items)
        summary[state] = int(summary.get(state, 0)) + 1
        closed_at_source += int(closed)
    summary["closed_at_source"] = closed_at_source
    if fall_out == FALL_OUT_APPLY:
        summary["removed_from_source_filter"] = await close_removed_from_filter(
            db, config, seen_keys, actor_id=current_user.id, sync_run_id=sync_run_id
        )
    else:
        summary["removed_from_source_filter_skipped_reason"] = fall_out
    config.last_sync_at = utc_now()
    config.last_sync_status = "completed"
    config.last_sync_summary_json = summary
    config.updated_by = current_user.id


async def _skipped_run(db: AsyncSession, *, config: WorkItemSyncConfig, current_user: User,
                       payload: dict[str, Any]) -> dict[str, Any]:
    """Another run of this configuration is still going: this start is recorded skipped (a person is told)."""
    from ..sync_window import SKIPPED_RUN_IN_PROGRESS

    run = _create_sync_run(config=config, current_user=current_user, limit=None, query_preview="", dry_run=False)
    run.status = "skipped"
    run.summary_json = {"skipped": SKIPPED_RUN_IN_PROGRESS, "trigger": trigger_of(payload),
                        "message": "A sync of this intake is already running."}
    run.completed_at = utc_now()
    db.add(run)
    await db.flush()
    return {"sync_run": serialize_sync_run(run), "items": [], "skipped": SKIPPED_RUN_IN_PROGRESS}


async def _require_no_foreign_items(db: AsyncSession, config: WorkItemSyncConfig,
                                    normalized: list[dict[str, Any]]) -> None:
    """The sync's one collision guard, before anything is written (a preview never asks another Workspace)."""
    await require_no_foreign_source_items(
        db, project_id=config.project_id, source_type="jira", source_instance=config.source_instance,
        source_keys=[item["source_key"] for item in normalized])


async def _preview_counts(
    db: AsyncSession, config: WorkItemSyncConfig, normalized: list[dict[str, Any]], summary: dict[str, Any]
) -> None:
    keys = [item["source_key"] for item in normalized]
    existing = set((await db.execute(select(WorkItem.source_key).where(
        WorkItem.project_id == config.project_id, WorkItem.source_type == "jira",
        WorkItem.source_instance == config.source_instance, WorkItem.source_key.in_(keys)
    ))).scalars()) if keys else set()
    summary.update(would_import=len(keys) - len(existing), already_in_work=len(existing))
