from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkCodingAuditEvent

AGENT_SESSION_EVENT_TYPES = ("agent_execution_started", "agent_execution_restarted")


async def list_work_item_agent_sessions(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    events = list(
        (
            await db.execute(
                select(WorkCodingAuditEvent)
                .where(
                    WorkCodingAuditEvent.work_item_id == work_item_id,
                    WorkCodingAuditEvent.event_type.in_(AGENT_SESSION_EVENT_TYPES),
                )
                .order_by(WorkCodingAuditEvent.created_at.desc())
            )
        ).scalars()
    )
    session_ids = [
        str((event.evidence_json or {}).get("session_id") or "").strip()
        for event in events
        if str((event.evidence_json or {}).get("session_id") or "").strip()
    ]
    sessions_by_id: dict[str, Session] = {}
    if session_ids:
        rows = (
            await db.execute(select(Session).where(Session.id.in_(list(dict.fromkeys(session_ids)))))
        ).scalars().all()
        sessions_by_id = {row.id: row for row in rows}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        evidence = event.evidence_json or {}
        session_id = str(evidence.get("session_id") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session = sessions_by_id.get(session_id)
        result.append(
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
    return result
