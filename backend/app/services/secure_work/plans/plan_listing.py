"""Cross-item Change Plan listing: one bounded, workspace-scoped summary read."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkChangePlan, WorkItem
from ..jira_values import iso
from .change_plans import PLAN_DECISIONS
from .plan_records import OPEN_PLAN_STATUSES

SUPERSEDED_PLAN_STATUS = "superseded"
KNOWN_PLAN_STATUSES = frozenset({*OPEN_PLAN_STATUSES, *PLAN_DECISIONS.values(), SUPERSEDED_PLAN_STATUS})
# The only persisted status that means "waiting for a reviewer".
PLAN_REVIEW_QUEUE_STATUSES = frozenset({"ready_for_review"})
PLAN_QUEUES = {"review": PLAN_REVIEW_QUEUE_STATUSES}

PLAN_LIST_DEFAULT_LIMIT = 50
PLAN_LIST_MAX_LIMIT = 200
CURSOR_MAX_LENGTH = 256
_CURSOR_VERSION = 1
_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class PlanListFilters:
    statuses: frozenset[str]
    include_superseded: bool
    project_id: str | None
    work_item_id: str | None
    limit: int
    cursor: tuple[datetime, str] | None


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def resolve_plan_list_filters(
    *,
    queue: str | None,
    statuses: list[str],
    include_superseded: bool | None,
    project_id: str | None,
    work_item_id: str | None,
    limit: int,
    cursor: str | None,
) -> PlanListFilters:
    # Every contradiction is a 422, never a silent reinterpretation.
    requested = {str(value or "").strip() for value in statuses}
    if "" in requested:
        raise _invalid("Empty status filter")
    unknown = sorted(requested - KNOWN_PLAN_STATUSES)
    if unknown:
        raise _invalid(f"Unknown Change Plan status: {', '.join(unknown)}")
    queue_key = (queue or "").strip() or None
    if queue_key is not None:
        if queue_key not in PLAN_QUEUES:
            raise _invalid(f"Unknown Change Plan queue: {queue_key}")
        if requested:
            raise _invalid("Use either queue or status, not both")
        requested = set(PLAN_QUEUES[queue_key])
    if SUPERSEDED_PLAN_STATUS in requested and include_superseded is False:
        raise _invalid("status=superseded contradicts include_superseded=false")
    # Asking for superseded plans explicitly includes them; otherwise the default hides them.
    effective_include = include_superseded if include_superseded is not None else SUPERSEDED_PLAN_STATUS in requested
    if not 1 <= limit <= PLAN_LIST_MAX_LIMIT:
        raise _invalid(f"limit must be between 1 and {PLAN_LIST_MAX_LIMIT}")
    return PlanListFilters(
        statuses=frozenset(requested),
        include_superseded=effective_include,
        project_id=(project_id or "").strip() or None,
        work_item_id=(work_item_id or "").strip() or None,
        limit=limit,
        cursor=decode_plan_cursor(cursor) if cursor else None,
    )


def _naive_utc(value: datetime) -> datetime:
    # Plan timestamps are stored as naive UTC; an aware value is normalized the same way.
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value


def encode_plan_cursor(sort_at: datetime, plan_id: str) -> str:
    payload = {"v": _CURSOR_VERSION, "at": _naive_utc(sort_at).isoformat(), "id": plan_id}
    raw = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_plan_cursor(cursor: str) -> tuple[datetime, str]:
    # The cursor is untrusted: bounded length, exact shape and types, or 422.
    if len(cursor) > CURSOR_MAX_LENGTH:
        raise _invalid("Malformed cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError):
        raise _invalid("Malformed cursor") from None
    if not isinstance(payload, dict) or set(payload) != {"v", "at", "id"}:
        raise _invalid("Malformed cursor")
    # Exactly the integer version: JSON true equals 1 in Python and must not pass.
    if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
        raise _invalid("Malformed cursor")
    at, plan_id = payload["at"], payload["id"]
    if not isinstance(at, str) or not isinstance(plan_id, str) or not _ID_PATTERN.match(plan_id):
        raise _invalid("Malformed cursor")
    try:
        # An offset can push a valid-looking time outside datetime's range (OverflowError).
        return _naive_utc(datetime.fromisoformat(at)), plan_id
    except (ValueError, OverflowError):
        raise _invalid("Malformed cursor") from None


def _sort_at():
    return WorkChangePlan.updated_at


def _scoped_conditions(scope: set[str] | None, filters: PlanListFilters) -> list[Any]:
    conditions: list[Any] = []
    if scope is not None:
        conditions.append(WorkItem.project_id.in_(sorted(scope)))
    if filters.project_id:
        conditions.append(WorkItem.project_id == filters.project_id)
    if filters.work_item_id:
        conditions.append(WorkChangePlan.work_item_id == filters.work_item_id)
    if not filters.include_superseded:
        conditions.append(WorkChangePlan.status != SUPERSEDED_PLAN_STATUS)
    return conditions


def _empty_counts(include_superseded: bool) -> dict[str, int]:
    return {
        status: 0
        for status in sorted(KNOWN_PLAN_STATUSES)
        if include_superseded or status != SUPERSEDED_PLAN_STATUS
    }


async def list_change_plan_summaries(
    db: AsyncSession, *, scope: set[str] | None, filters: PlanListFilters
) -> dict[str, Any]:
    if scope is not None and filters.project_id and filters.project_id not in scope:
        raise HTTPException(status_code=403, detail="Workspace is outside your Work access")
    counts = _empty_counts(filters.include_superseded)
    if scope is not None and not scope:
        # No workspace access: nothing to read, and items without a workspace are admin-only.
        return {"items": [], "next_cursor": None, "status_counts": counts}

    conditions = _scoped_conditions(scope, filters)
    count_rows = await db.execute(
        select(WorkChangePlan.status, func.count(WorkChangePlan.id))
        .join(WorkItem, WorkItem.id == WorkChangePlan.work_item_id)
        .where(*conditions)
        .group_by(WorkChangePlan.status)
    )
    for status, total in count_rows.all():
        counts[str(status)] = int(total)

    sort_at = _sort_at().label("sort_at")
    page_conditions = list(conditions)
    if filters.statuses:
        page_conditions.append(WorkChangePlan.status.in_(sorted(filters.statuses)))
    if filters.cursor is not None:
        cursor_at, cursor_id = filters.cursor
        page_conditions.append(
            or_(_sort_at() < cursor_at, and_(_sort_at() == cursor_at, WorkChangePlan.id < cursor_id))
        )
    rows = (
        await db.execute(
            select(
                WorkChangePlan.id,
                WorkChangePlan.work_item_id,
                WorkChangePlan.version,
                WorkChangePlan.status,
                WorkChangePlan.title,
                WorkChangePlan.workflow_id,
                WorkChangePlan.supersedes_plan_id,
                WorkChangePlan.evidence_json["plan_type"].as_string().label("plan_type"),
                WorkChangePlan.open_questions_json,
                WorkChangePlan.acceptance_criteria_json,
                WorkChangePlan.change_units_json,
                WorkChangePlan.created_by,
                User.display_name,
                User.username,
                WorkChangePlan.decided_by,
                WorkChangePlan.created_at,
                WorkChangePlan.updated_at,
                WorkChangePlan.decided_at,
                WorkChangePlan.approved_at,
                sort_at,
                WorkItem.source_key,
                WorkItem.title.label("work_item_title"),
                WorkItem.project_id,
                WorkItem.work_state,
                WorkItem.source_url,
            )
            .join(WorkItem, WorkItem.id == WorkChangePlan.work_item_id)
            .outerjoin(User, User.id == WorkChangePlan.created_by)
            .where(*page_conditions)
            .order_by(sort_at.desc(), WorkChangePlan.id.desc())
            .limit(filters.limit + 1)
        )
    ).all()
    page = rows[: filters.limit]
    next_cursor = None
    if len(rows) > filters.limit:
        last = page[-1]
        next_cursor = encode_plan_cursor(_as_datetime(last.sort_at), last.id)
    return {"items": [_summary(row) for row in page], "next_cursor": next_cursor, "status_counts": counts}


def _as_datetime(value: Any) -> datetime:
    # SQLite returns the coalesced expression as text; PostgreSQL returns a datetime.
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _summary(row: Any) -> dict[str, Any]:
    plan_type = row.plan_type if isinstance(row.plan_type, str) and row.plan_type else None
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "version": int(row.version or 0),
        "status": row.status,
        "title": row.title,
        "workflow_id": row.workflow_id,
        "supersedes_plan_id": row.supersedes_plan_id,
        "plan_type": plan_type,
        "open_questions_count": _length(row.open_questions_json),
        "acceptance_criteria_count": _length(row.acceptance_criteria_json),
        "change_unit_count": _length(row.change_units_json),
        "created_by": row.created_by,
        "created_by_name": row.display_name or row.username or None,
        "decided_by": row.decided_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "decided_at": iso(row.decided_at),
        "approved_at": iso(row.approved_at),
        "work_item": {
            "id": row.work_item_id,
            "source_key": row.source_key,
            "title": row.work_item_title,
            "project_id": row.project_id,
            "work_state": row.work_state,
            "source_url": row.source_url,
        },
    }
