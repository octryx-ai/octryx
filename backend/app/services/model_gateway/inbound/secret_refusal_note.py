"""Which kind of secret the gateway refused, on the run's timeline: the fixed kinds, never the text."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.enforcement_inbound import InboundPlan

EVENT = "secret_refused"


async def note_secret_refusal(db: AsyncSession, session_id: str | None, plan: InboundPlan) -> None:
    from .refusals import REASON_SECRET_DETECTED

    if getattr(plan.refusal, "reason", None) != REASON_SECRET_DETECTED or not session_id:
        return
    from ...workflow_runs.records import active_run_for_session, record_event

    run = await active_run_for_session(db, session_id)
    if run is None:
        return
    record_event(db, run, EVENT, node_id=run.current_node_id, detail={"found": [dict(item) for item in plan.found]})
    await db.commit()


__all__ = ["EVENT", "note_secret_refusal"]
