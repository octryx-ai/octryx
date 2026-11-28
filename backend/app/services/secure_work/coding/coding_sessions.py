from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    Session,
    WorkChangePlan,
    WorkCodingAuditEvent,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemStateEvent,
    WorkPullRequest,
)
from ..plan_serializers import serialize_change_plan, serialize_change_unit
from ..pull_requests.record_identity import in_item_workspace
from ..serializers import serialize_pull_request, serialize_state_event, serialize_work_item
from .coding_review_summary import review_summaries_for_items


async def list_coding_session_candidates(
    db: AsyncSession,
    *,
    project_scope: set[str] | None,
    limit: int = 1000,
) -> dict[str, object]:
    """Coding cockpit candidates with their plans, units, state events and agent sessions."""
    capped_limit = max(1, min(limit, 5000))
    if project_scope is not None and not project_scope:
        return {"items": [], "count": 0, "limit": capped_limit}
    stmt = select(WorkItem)
    if project_scope is not None:
        # Scoped in SQL before the limit and the count, so no foreign item or its plan evidence is loaded
        stmt = stmt.where(WorkItem.project_id.in_(sorted(project_scope)))
    items = (
        (
            await db.execute(
                stmt.order_by(
                    WorkItem.last_source_updated_at.desc().nullslast(),
                    WorkItem.updated_at.desc().nullslast(),
                )
                .limit(capped_limit)
            )
        )
        .scalars()
        .all()
    )
    item_ids = [item.id for item in items]
    plans_by_item: dict[str, list[WorkChangePlan]] = defaultdict(list)
    units_by_item: dict[str, list[WorkItemChangeUnit]] = defaultdict(list)
    events_by_item: dict[str, list[WorkItemStateEvent]] = defaultdict(list)
    agent_sessions_by_item: dict[str, list[dict[str, object]]] = defaultdict(list)
    pull_requests_by_item: dict[str, list[WorkPullRequest]] = defaultdict(list)
    if item_ids:
        # The item's pull requests come from work_pull_requests, the one PR source.
        for pull_request in (await db.execute(
            select(WorkPullRequest).where(WorkPullRequest.work_item_id.in_(item_ids), in_item_workspace())
            .order_by(WorkPullRequest.updated_at.desc())
        )).scalars():
            pull_requests_by_item[pull_request.work_item_id].append(pull_request)
        plan_rows = (
            (
                await db.execute(
                    select(WorkChangePlan)
                    .where(WorkChangePlan.work_item_id.in_(item_ids))
                    .order_by(WorkChangePlan.version.desc(), WorkChangePlan.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        unit_rows = (
            (
                await db.execute(
                    select(WorkItemChangeUnit)
                    .where(WorkItemChangeUnit.work_item_id.in_(item_ids))
                    .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        event_rows = (
            (
                await db.execute(
                    select(WorkItemStateEvent)
                    .where(WorkItemStateEvent.work_item_id.in_(item_ids))
                    .order_by(WorkItemStateEvent.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        audit_rows = (
            (
                await db.execute(
                    select(WorkCodingAuditEvent)
                    .where(
                        WorkCodingAuditEvent.work_item_id.in_(item_ids),
                        WorkCodingAuditEvent.event_type.in_(["agent_execution_started", "agent_execution_restarted"]),
                    )
                    .order_by(WorkCodingAuditEvent.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        session_ids = [
            str((event.evidence_json or {}).get("session_id") or "").strip()
            for event in audit_rows
            if str((event.evidence_json or {}).get("session_id") or "").strip()
        ]
        sessions_by_id: dict[str, Session] = {}
        if session_ids:
            session_result = await db.execute(select(Session).where(Session.id.in_(list(dict.fromkeys(session_ids)))))
            session_rows = session_result.scalars().all()
            sessions_by_id = {session.id: session for session in session_rows}
        for plan in plan_rows:
            plans_by_item[plan.work_item_id].append(plan)
        for unit in unit_rows:
            units_by_item[unit.work_item_id].append(unit)
        for event in event_rows:
            events_by_item[event.work_item_id].append(event)
        for event in audit_rows:
            evidence = event.evidence_json or {}
            session_id = str(evidence.get("session_id") or "").strip()
            if not session_id:
                continue
            session = sessions_by_id.get(session_id)
            agent_sessions_by_item[event.work_item_id].append(
                {
                    "id": session_id,
                    "status": session.status if session else "unknown",
                    "run_status": session.run_status if session else None,
                    "agent_type": session.agent_type if session else "coding",
                    "chat_url": f"/chat?session_id={session_id}",
                    "event_type": event.event_type,
                    "event_id": event.id,
                    "started_at": event.created_at.isoformat() if event.created_at else None,
                    "pipeline_run_id": event.pipeline_run_id,
                    "change_plan_id": evidence.get("change_plan_id"),
                    "restart": bool(evidence.get("restart_from_scratch")),
                    "restart_reason": evidence.get("restart_reason"),
                }
            )
    # The coding audit's reviewer verdict for every listed item, batched.
    review_summaries = await review_summaries_for_items(db, item_ids, plans_by_item, units_by_item)
    return {
        "items": [
            {
                "work_item": serialize_work_item(item),
                "change_plans": [serialize_change_plan(plan) for plan in plans_by_item[item.id]],
                "change_units": [serialize_change_unit(unit) for unit in units_by_item[item.id]],
                "state_events": [serialize_state_event(event) for event in events_by_item[item.id]],
                "agent_sessions": agent_sessions_by_item[item.id],
                "pull_requests": [serialize_pull_request(row) for row in pull_requests_by_item[item.id]],
                "review_summary": review_summaries[item.id],
            }
            for item in items
        ],
        "count": len(items),
        "limit": capped_limit,
    }
