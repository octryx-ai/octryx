"""The handover context of a platform work item: what a fresh worker needs to continue."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem
from .platform_item_sessions import _linked_sessions
from .session_handover import linked_session_digest


async def build_work_item_context(
    db: AsyncSession,
    *,
    item: WorkItem,
    include_session_digests: bool = True,
    max_sessions: int = 5,
    digest_tail_chars: int = 3000,
) -> dict[str, Any]:
    """The handover bundle: everything a fresh worker needs to continue.

    Aggregates the item, its epic children, recent state history, the latest
    change plan, progress notes, and the linked sessions with their
    conversation digests — worker 2 starts with worker 1's full context.
    """
    context: dict[str, Any] = {
        "work_item": {
            "id": item.id,
            "source_key": item.source_key,
            "source_type": item.source_type,
            "title": item.title,
            "description": item.description or "",
            "issue_type": item.issue_type,
            "work_state": item.work_state,
            "priority": item.priority,
            "epic_key": item.epic_key,
            "labels": list(item.labels_json or []),
            "project_id": item.project_id,
        }
    }

    if str(item.issue_type or "") == "epic":
        context["children"] = await _epic_children(db, item)
    context["state_history"] = await _state_history(db, item)
    context["latest_plan"] = await _latest_plan(db, item)

    fields = item.source_fields_json if isinstance(item.source_fields_json, dict) else {}
    context["notes"] = [entry for entry in fields.get("platform_notes") or [] if isinstance(entry, dict)][-15:]

    sessions = await _linked_session_entries(
        db,
        item,
        include_session_digests=include_session_digests,
        max_sessions=max_sessions,
        digest_tail_chars=digest_tail_chars,
    )
    context["linked_sessions"] = sessions
    context["unknowns"] = (
        ["No sessions linked yet - link the working session via work_item_link_session."]
        if not sessions
        else []
    )
    return context


async def _epic_children(db: AsyncSession, item: WorkItem) -> list[dict[str, Any]]:
    children = (
        await db.execute(
            select(WorkItem)
            .where(WorkItem.epic_key == item.source_key)
            .order_by(WorkItem.created_at)
        )
    ).scalars().all()
    return [
        {"source_key": child.source_key, "title": child.title, "work_state": child.work_state}
        for child in children
    ]


async def _state_history(db: AsyncSession, item: WorkItem) -> list[dict[str, Any]]:
    from ...models import WorkItemStateEvent

    events = (
        await db.execute(
            select(WorkItemStateEvent)
            .where(WorkItemStateEvent.work_item_id == item.id, WorkItemStateEvent.dry_run.is_(False))
            .order_by(WorkItemStateEvent.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return [
        {
            "from": event.from_state,
            "to": event.to_state,
            "reason": event.reason,
            "at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in events
    ]


async def _latest_plan(db: AsyncSession, item: WorkItem) -> dict[str, Any] | None:
    from ...models import WorkChangePlan

    plan = (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == item.id, WorkChangePlan.status != "superseded")
            .order_by(WorkChangePlan.version.desc())
            .limit(1)
        )
    ).scalars().first()
    return (
        None
        if plan is None
        else {
            "id": plan.id,
            "version": plan.version,
            "status": plan.status,
            "title": plan.title,
            "acceptance_criteria": list(plan.acceptance_criteria_json or []),
            "open_questions": list(plan.open_questions_json or []),
        }
    )


async def _linked_session_entries(
    db: AsyncSession,
    item: WorkItem,
    *,
    include_session_digests: bool,
    max_sessions: int,
    digest_tail_chars: int,
) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for link in _linked_sessions(item)[-max_sessions:]:
        entry: dict[str, Any] = {
            "client_session_id": link.get("client_session_id"),
            "linked_at": link.get("linked_at"),
        }
        if include_session_digests and link.get("client_session_id"):
            digest = await linked_session_digest(
                db,
                project_id=item.project_id,
                client_session_id=str(link["client_session_id"]),
                tail_chars=digest_tail_chars,
            )
            if digest is not None:
                entry.update(digest)
        sessions.append(entry)
    return sessions
