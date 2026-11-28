from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkItemSyncConfig,
    WorkItemSyncRun,
)
from ...error_facts import error_text, error_type
from ..intake.run_counts import run_counts
from ..intake.runs import trigger_of
from ..jira_values import object_value, optional_int
from ..serializers import serialize_sync_run
from .jira_filters import (
    build_jira_query_preview,
    issue_matches_filters,
)
from .jira_item_upsert import (
    FALL_OUT_APPLY,
    close_removed_from_filter,
    fall_out_check,
    preview_removed_from_filter,
)
from .jira_mapping import jira_issue_to_work_item_payload
from .jira_run_failure import record_failed_run, run_values
from .jira_scope import (
    guard_intake,
    issue_allowed,
    restrict_jql,
    scope_links,
    scope_parent,
    unsendable_query,
)
from .jira_sync_config import get_jira_sync_config
from .jira_sync_records import (
    _block_run,
    _build_blocked_summary,
    _build_summary,
    _complete_run,
    _create_sync_run,
    _persist_sync_items,
    _preview_counts,
    _require_no_foreign_items,
    _skipped_run,
)
from .jira_sync_source import _resolve_source_issues

logger = logging.getLogger(__name__)


async def run_jira_work_item_sync(
    db: AsyncSession,
    *,
    config_id: str,
    current_user: User,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    # One run at a time per configuration; previews and request-supplied issue lists bypass the lease and window.
    from ..sync_window import acquire_sync_lease, sync_window

    if dry_run or isinstance(payload.get("issues"), list):
        return await _run_jira_sync(db, config_id=config_id, current_user=current_user, payload=payload,
                                    dry_run=dry_run, window=None)
    config = await get_jira_sync_config(db, config_id)
    from ...observability.sync_metrics import record_run

    if not await acquire_sync_lease(db, config_id):
        record_run(kind="jira", window="none", outcome="skipped")
        return await _skipped_run(db, config=config, current_user=current_user, payload=payload)
    started = time.monotonic()
    window: dict[str, Any] = {}
    outcome, items = "failed", 0
    try:
        window = await sync_window(db, config, payload)
        result = await _run_jira_sync(db, config_id=config_id, current_user=current_user, payload=payload,
                                      dry_run=False, window=window)
        run = dict(result.get("sync_run") or {})
        outcome = str(run.get("status") or "completed")
        items = int(dict(run.get("summary") or {}).get("total_source") or 0)
        return result
    finally:
        record_run(kind="jira", window=str(window.get("mode") or "none"), outcome=outcome, items=items,
                   seconds=time.monotonic() - started)
        await _release_lease_isolated(config_id)


async def _release_lease_isolated(config_id: str) -> None:
    # A session of its own: a failed run's rollback must not keep the lease (it would expire).
    from ....db import core as db_core
    from ..sync_window import release_sync_lease

    try:
        async with db_core.async_session_factory() as own:
            await release_sync_lease(own, config_id)
            await own.commit()
    except Exception:  # noqa: BLE001 - the lease expires by itself (sync_window.RUN_LEASE)
        logger.warning("jira_sync.lease_release_failed config=%s", config_id, exc_info=True)


async def _run_jira_sync(
    db: AsyncSession,
    *,
    config_id: str,
    current_user: User,
    payload: dict[str, Any],
    dry_run: bool,
    window: dict[str, Any] | None,
) -> dict[str, Any]:
    from ..sync_window import MODE_INCREMENTAL, incremental_jql

    config = await get_jira_sync_config(db, config_id)
    incremental = bool(window and window.get("mode") == MODE_INCREMENTAL)
    limit = optional_int(payload.get("limit"))
    if limit is None and not dry_run:
        sync_options = object_value(config.sync_options_json)
        limit = optional_int(sync_options.get("max_results")) or optional_int(sync_options.get("manual_limit"))
    query_preview = (incremental_jql(config.filters_json or {}, int(window["minutes"])) if incremental
                     else build_jira_query_preview(config.filters_json or {}))
    run = _create_sync_run(
        config=config,
        current_user=current_user,
        limit=limit,
        query_preview=query_preview,
        dry_run=dry_run,
    )
    db.add(run)
    await db.flush()
    try:
        # Refused outside the allowlist; every query is restricted to it.
        allowed = await guard_intake(db, config)
        unsendable = unsendable_query(query_preview)  # unbalanced JQL is never sent
        if unsendable is None:  # an unsafe query is never confined or sent: the run is blocked below
            query_preview = run.query_preview = restrict_jql(query_preview, allowed)
        source = unsendable or await _resolve_source_issues(
            db,
            config=config,
            payload=payload,
            limit=limit,
            query_preview=query_preview,
        )
        if not source["configured"]:
            summary = _build_blocked_summary(query_preview=query_preview, dry_run=dry_run, source=source)
            summary["trigger"] = trigger_of(payload)
            _block_run(run, config=config, summary=summary)
            await db.flush()
            return {"sync_run": serialize_sync_run(run), "items": []}
        return await _sync_source_issues(
            db, config=config, current_user=current_user, payload=payload, dry_run=dry_run, window=window,
            incremental=incremental, limit=limit, run=run, source=source, allowed=allowed,
            query_preview=query_preview,
        )
    except Exception as exc:
        # Recorded in its own transaction, so the request's rollback never loses it.
        await record_failed_run(db, config_id=config_id, values=run_values(run), exc=exc,
                                trigger=trigger_of(payload))
        raise


async def _sync_source_issues(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    current_user: User,
    payload: dict[str, Any],
    dry_run: bool,
    window: dict[str, Any] | None,
    incremental: bool,
    limit: int | None,
    run: WorkItemSyncRun,
    source: dict[str, Any],
    allowed: Any,
    query_preview: str,
) -> dict[str, Any]:
    raw_issues, filtered_issues, fall_out, seen_keys, left_keys = _select_issues(
        config, payload, source=source, allowed=allowed, limit=limit, incremental=incremental
    )
    normalized, mapping_errors, unmapped_statuses, category_statuses = _map_issues(filtered_issues, config, allowed)
    summary = _build_summary(
        query_preview=query_preview,
        source_count=int(source.get("source_count") or len(raw_issues)),
        filtered_count=len(filtered_issues),
        valid_count=len(normalized),
        dry_run=dry_run,
        source=source,
    )
    summary.update(trigger=trigger_of(payload), **run_counts(normalized=normalized, source=source,
                                                            sync_options=config.sync_options_json))
    if allowed is not None:
        # Whether issues were filtered, never how many of another project exist.
        filtered_outside = len(raw_issues) < len(source["issues"])
        summary.update(allowed_projects=sorted(allowed), filtered_outside_allowlist=filtered_outside)
    _report_mapping(summary, config, mapping_errors, unmapped_statuses, category_statuses)
    if dry_run:  # the preview's "would import" and "already in Work", within the intake's Workspace only
        await _preview_counts(db, config, normalized, summary)
    else:
        await _require_no_foreign_items(db, config, normalized)
    # Every issue the filter returned counts as seen, a malformed one included: it is still in the filter.
    if dry_run and fall_out == FALL_OUT_APPLY:
        summary["would_mark_removed"] = await preview_removed_from_filter(db, config, seen_keys)
    if window:
        summary.update(window=window["mode"], **({"window_minutes": window["minutes"]} if incremental else {}),
                       **({"full_reason": window.get("reason")} if not incremental else {}))
    if not dry_run:
        await _persist_sync_items(db, config=config, current_user=current_user, normalized=normalized,
                                  summary=summary, fall_out=fall_out, seen_keys=seen_keys, sync_run_id=run.id)
        if left_keys:
            from .jira_item_upsert import _intake_items

            known = {row.source_key for row in await _intake_items(db, config)}
            summary["left_filter"] = await close_removed_from_filter(
                db, config, known - (left_keys & known), actor_id=current_user.id, sync_run_id=run.id)
    _complete_run(run, summary=summary, normalized=normalized)
    await db.flush()
    return {"sync_run": serialize_sync_run(run), "items": run.sample_items_json}


def _select_issues(
    config: WorkItemSyncConfig,
    payload: dict[str, Any],
    *,
    source: dict[str, Any],
    allowed: Any,
    limit: int | None,
    incremental: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, set[str], set[str]]:
    from ..sync_window import MODE_INCREMENTAL

    raw_issues = [issue for issue in source["issues"] if issue_allowed(issue, allowed)]
    filtered_issues = [issue for issue in raw_issues if issue_matches_filters(issue, config.filters_json or {})]
    fall_out = fall_out_check(payload, source=source, limit=limit, matched_count=len(filtered_issues))
    seen_keys = {str(issue.get("key") or "").strip() for issue in filtered_issues}
    # An incremental run sees only what changed: it never concludes an unseen item left the filter; a changed
    # issue that no longer matches it (closed, moved) did leave it (``left_keys``).
    left_keys = {str(issue.get("key") or "").strip() for issue in raw_issues} - seen_keys if incremental \
        else set()
    if incremental:
        fall_out = MODE_INCREMENTAL
    if limit is not None:
        filtered_issues = filtered_issues[:limit]
    return raw_issues, filtered_issues, fall_out, seen_keys, left_keys


def _map_issues(
    filtered_issues: list[dict[str, Any]], config: WorkItemSyncConfig, allowed: Any
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, int], dict[str, int]]:
    # Item-level isolation: a malformed issue is skipped and reported in the summary, never sinks the run.
    normalized: list[dict[str, Any]] = []
    mapping_errors: list[dict[str, str]] = []
    unmapped_statuses: dict[str, int] = {}
    category_statuses: dict[str, int] = {}
    for issue in filtered_issues:
        try:
            item_payload = jira_issue_to_work_item_payload(issue, config)
        except Exception as exc:  # noqa: BLE001 - isolate per-issue failures
            issue_key = str(issue.get("key") or "?")
            mapping_errors.append({"issue": issue_key, "error": error_text("jira_issue_mapping_failed", exc)})
            logger.warning("jira_sync.issue_mapping_failed issue=%s error_type=%s", issue_key, error_type(exc))
            continue
        item_payload["linked_issues_json"] = scope_links(item_payload["linked_issues_json"], allowed)  # scoped
        item_payload["parent_key"] = scope_parent(item_payload.get("parent_key"), allowed)  # scoped
        item_payload["epic_key"] = scope_parent(item_payload.get("epic_key"), allowed)  # scoped
        normalized.append(item_payload)
        status_value = str(item_payload.get("source_status") or "")
        mapping_source = item_payload["source_fields_json"]["status_mapping"]["source"]
        if mapping_source in ("unmapped", "status_category") and status_value:
            reported = unmapped_statuses if mapping_source == "unmapped" else category_statuses
            reported[status_value] = reported.get(status_value, 0) + 1
    return normalized, mapping_errors, unmapped_statuses, category_statuses


def _report_mapping(
    summary: dict[str, Any],
    config: WorkItemSyncConfig,
    mapping_errors: list[dict[str, str]],
    unmapped_statuses: dict[str, int],
    category_statuses: dict[str, int],
) -> None:
    if mapping_errors:
        summary["mapping_errors"] = mapping_errors[:20]
        summary["mapping_error_count"] = len(mapping_errors)
    if category_statuses:
        # Mapped by Jira's statusCategory only; an explicit mapping makes them precise.
        summary["status_category_statuses"] = category_statuses
    if unmapped_statuses:
        # Statuses that defaulted to "intake": extend status_state_mapping
        # in sync_options to map them explicitly.
        summary["unmapped_statuses"] = unmapped_statuses
        logger.warning(
            "jira_sync.unmapped_statuses config=%s statuses=%s", config.id, sorted(unmapped_statuses)
        )
