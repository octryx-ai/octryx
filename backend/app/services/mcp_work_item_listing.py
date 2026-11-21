"""The ``work_item_list`` secure-work MCP tool: open work items to pick up, ready-to-work first."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, WorkItem
from ..models.runtime.secure_work import WorkChangePlan
from .mcp_work_access import WorkGrantScope, require_listing_project
from .secure_work.work_item_listing import TERMINAL_STATES as _TERMINAL_STATES

_PRIORITY_RANK = {
    "highest": 0, "critical": 0, "blocker": 0,
    "high": 1, "major": 1,
    "normal": 2, "medium": 2,
    "low": 3, "lowest": 4, "minor": 4,
}


def _priority_rank(value: Any) -> int:
    return _PRIORITY_RANK.get(str(value or "").strip().lower(), 2)


async def mcp_work_item_list(
    db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Open work items to pick up - the actionable task list.

    Defaults to non-terminal states (the real backlog). Filters: project_id,
    state, assignee (or mine=true), issue_type, source_type, limit. Each row
    carries readiness signals (has_plan, open_questions, sessions) so the
    caller sees not just WHAT but how ready each task is.
    """
    accessible = sorted(scope.listing_project_ids)
    project_id = str(arguments.get("project_id") or "").strip()
    if project_id:
        require_listing_project(scope, project_id)
    limit = max(1, min(int(arguments.get("limit") or 25), 100))

    stmt = select(WorkItem)
    stmt = stmt.where(WorkItem.project_id == project_id) if project_id else stmt.where(
        WorkItem.project_id.in_(accessible)
    )
    state = str(arguments.get("state") or "").strip()
    if state:
        stmt = stmt.where(WorkItem.work_state == state)
    else:
        stmt = stmt.where(WorkItem.work_state.notin_(_TERMINAL_STATES))
    stmt = await _assignee_and_type_filters(db, stmt, user=user, arguments=arguments)

    rows = (await db.execute(stmt.order_by(WorkItem.updated_at.desc()).limit(limit * 4))).scalars().all()

    # Readiness signal: which of these items have a live (non-superseded) plan.
    planned = await _planned_item_ids(db, [row.id for row in rows])

    items = [_listed_item(row, planned) for row in rows]
    # Ready-to-work first: planned items, then by priority, then recency.
    items.sort(key=lambda it: (not it["has_plan"], _priority_rank(it["priority"])))
    items = items[:limit]
    return {"items": items, "count": len(items), "filter_state": state or "open"}


async def _assignee_and_type_filters(db: AsyncSession, stmt: Any, *, user: User, arguments: dict[str, Any]) -> Any:
    assignee = str(arguments.get("assignee") or "").strip()
    if arguments.get("mine") and not assignee:
        # The user's own items: their username, email or a linked account (a Jira Cloud assignee is an account id).
        from .linked_accounts.resolution import account_identifiers

        mine = {user.username, user.email, *await account_identifiers(db, user.id)} - {None, ""}
        stmt = stmt.where(func.lower(WorkItem.assignee).in_({str(name).lower() for name in mine}))
    elif assignee:
        stmt = stmt.where(WorkItem.assignee == assignee)
    for field, column in (("issue_type", WorkItem.issue_type), ("source_type", WorkItem.source_type)):
        value = str(arguments.get(field) or "").strip()
        if value:
            stmt = stmt.where(column == value)
    return stmt


async def _planned_item_ids(db: AsyncSession, ids: list[str]) -> set[str]:
    planned: set[str] = set()
    if ids:
        planned = set(
            (
                await db.execute(
                    select(WorkChangePlan.work_item_id)
                    .where(WorkChangePlan.work_item_id.in_(ids), WorkChangePlan.status != "superseded")
                    .distinct()
                )
            ).scalars().all()
        )
    return planned


def _listed_item(row: WorkItem, planned: set[str]) -> dict[str, Any]:
    fields = row.source_fields_json if isinstance(row.source_fields_json, dict) else {}
    return {
        "source_key": row.source_key,
        "title": row.title,
        "work_state": row.work_state,
        "priority": row.priority,
        "issue_type": row.issue_type,
        "source_type": row.source_type,
        "assignee": row.assignee,
        "epic_key": row.epic_key,
        "has_plan": row.id in planned,
        "sessions": len([s for s in (fields.get("linked_sessions") or []) if isinstance(s, dict)]),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
