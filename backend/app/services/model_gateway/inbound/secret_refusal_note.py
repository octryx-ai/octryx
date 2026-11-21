"""Which kind of secret the gateway refused, on the run's timeline.

Without this a refused call (``secret_detected_in_prompt``) names nothing, and a false alarm cannot be told from a real
secret. The run records the fixed kinds (``secret_scan``: private_key, aws_access_key_id, vendor_token, jwt, …) —
never the matched text. They come from the request's scan (``content_routing.gateway_plan.InboundPlan.found``:
bounded and redacted); the request is never scanned a second time.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_routing.gateway_plan import InboundPlan

EVENT = "secret_refused"


async def note_secret_refusal(db: AsyncSession, session_id: str | None, plan: InboundPlan) -> None:
    """Record the kinds on the session's active run when the refusal is the secret scan's (else nothing)."""
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
