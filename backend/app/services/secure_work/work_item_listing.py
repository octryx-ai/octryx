"""The Work item list: lean rows, paginated."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem
from .automation_eligibility import work_item_automation_eligibility
from .jira.jira_filters import work_item_matches_json_filters
from .jira.jira_item_details import work_item_detail_fields
from .jira_values import iso, string_list

# States in which a Work item is finished: "open" (the backlog, the task list on the phone) means none of these.
TERMINAL_STATES = frozenset({"done", "rejected", "cancelled", "canceled", "closed", "resolved", "superseded"})
LIST_DEFAULT_LIMIT = 100
LIST_MAX_LIMIT = 1000
JSON_FILTER_SCAN_LIMIT = 5000
# Detail-only fields: present on ``GET /work-items/{id}``, never in a list row.
DETAIL_ONLY_FIELDS = (
    "description",
    "source_fields",
    "comments",
    "watchers",
    "watchers_display",
    "components",
    "linked_issues",
)


def serialize_work_item_row(row: WorkItem) -> dict[str, Any]:
    details = work_item_detail_fields(row)
    return {
        "id": row.id,
        "project_id": row.project_id,
        "sync_config_id": row.sync_config_id,
        "source_type": row.source_type,
        "source_instance": row.source_instance,
        "source_id": row.source_id,
        "source_project_key": row.source_project_key,
        "source_key": row.source_key,
        "source_url": row.source_url,
        "title": row.title,
        "issue_type": row.issue_type,
        "source_status": row.source_status,
        "priority": row.priority,
        "assignee": row.assignee,
        "assignee_display": details["assignee_display"],
        "reporter": row.reporter,
        "reporter_display": details["reporter_display"],
        "labels": list(row.labels_json or []),
        "fix_versions": list(row.fix_versions_json or []),
        "parent_key": row.parent_key,
        "epic_key": row.epic_key,
        "sprint": details["sprint"],
        "board": details["board"],
        "status_mapping": details["status_mapping"],
        "comments_total": details["comments_total"],
        "automation_eligibility": work_item_automation_eligibility(row),
        "work_state": row.work_state,
        "sync_state": row.sync_state,
        "source_created_at": iso(row.source_created_at),
        "last_source_updated_at": iso(row.last_source_updated_at),
        "imported_at": iso(row.imported_at),
        "synced_at": iso(row.synced_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _page(items: list[dict[str, Any]], *, total: int, limit: int, offset: int) -> dict[str, Any]:
    next_offset = offset + len(items)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset if next_offset < total else None,
    }


async def list_work_items(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    sync_config_id: str | None = None,
    source_status: str | None = None,
    work_state: str | None = None,
    sync_state: str | None = None,
    assignees: list[str] | None = None,
    labels: list[str] | None = None,
    fix_versions: list[str] | None = None,
    sprint_ids: list[str] | None = None,
    sprint_names: list[str] | None = None,
    limit: int = LIST_DEFAULT_LIMIT,
    offset: int = 0,
    project_scope: set[str] | None = None,
    open_only: bool = False,
    assignee_identifiers: set[str] | None = None,
    search: str | None = None,
    with_state_counts: bool = False,
) -> dict[str, Any]:
    """One page of lean Work item rows; ``project_scope`` ``None`` is a platform admin."""
    conditions = []
    if project_scope is not None:  # the caller's Workspaces only (None: platform admin)
        conditions.append(WorkItem.project_id.in_(project_scope))
    for column, value in (
        (WorkItem.project_id, project_id),
        (WorkItem.sync_config_id, sync_config_id),
        (WorkItem.source_status, source_status),
        (WorkItem.sync_state, sync_state),
    ):
        if value:
            conditions.append(column == value)
    normalized_assignees = string_list(assignees)
    if normalized_assignees:
        conditions.append(WorkItem.assignee.in_(normalized_assignees))
    if open_only:
        conditions.append(WorkItem.work_state.notin_(TERMINAL_STATES))
    if assignee_identifiers is not None:
        mine = {str(value).lower() for value in assignee_identifiers if value}
        conditions.append(func.lower(WorkItem.assignee).in_(mine) if mine else WorkItem.id.is_(None))
    needle = (search or "").strip()[:100]
    if needle:
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(WorkItem.title.ilike(pattern, escape="\\") | WorkItem.source_key.ilike(pattern, escape="\\"))
    state_free = list(conditions)  # the filters but the state, for ``state_counts``
    if work_state:
        conditions.append(WorkItem.work_state == work_state)
    limit = max(1, min(int(limit), LIST_MAX_LIMIT))
    offset = max(0, int(offset))
    ordered = select(WorkItem).where(*conditions).order_by(WorkItem.updated_at.desc(), WorkItem.id.desc())

    if any(string_list(value) for value in (labels, fix_versions, sprint_ids, sprint_names)):
        scanned = (await db.execute(ordered.limit(JSON_FILTER_SCAN_LIMIT))).scalars().all()
        matches = [
            row for row in scanned
            if work_item_matches_json_filters(
                row, labels=labels, fix_versions=fix_versions, sprint_ids=sprint_ids, sprint_names=sprint_names
            )
        ]
        rows = matches[offset:offset + limit]
        return _page([serialize_work_item_row(row) for row in rows], total=len(matches), limit=limit, offset=offset)

    total = int((await db.execute(select(func.count(WorkItem.id)).where(*conditions))).scalar_one())
    rows = (await db.execute(ordered.offset(offset).limit(limit))).scalars().all()
    page = _page([serialize_work_item_row(row) for row in rows], total=total, limit=limit, offset=offset)
    if with_state_counts:
        counted = await db.execute(
            select(WorkItem.work_state, func.count(WorkItem.id)).where(*state_free).group_by(WorkItem.work_state)
        )
        page["state_counts"] = {str(state or ""): int(count) for state, count in counted.all()}
    return page


__all__ = [
    "DETAIL_ONLY_FIELDS",
    "LIST_DEFAULT_LIMIT",
    "LIST_MAX_LIMIT",
    "list_work_items",
    "serialize_work_item_row",
]
