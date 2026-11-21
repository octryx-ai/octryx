"""The outbound webhook event catalog and the retry schedule."""

from __future__ import annotations

from fastapi import HTTPException

# One catalog of events the platform actually emits. knowledge.updated was never emitted;
# worker.monitor.alert was emitted and refused every time.
ALLOWED_OUTBOUND_WEBHOOK_EVENTS = {
    "task.completed",
    "task.failed",
    "approval.requested",
    "session.completed",
    "alert.triggered",
    "worker.monitor.alert",
    # a run or device job got a problem (looping, silent, stalled, paused, failed) / it cleared.
    "problem.raised",
    "problem.cleared",
}
OUTBOUND_WEBHOOK_RETRY_DELAYS_SECONDS = [5, 30, 120, 600]


def _normalize_event_types(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if value not in ALLOWED_OUTBOUND_WEBHOOK_EVENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported outbound webhook event: {value}",
            )
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise HTTPException(status_code=422, detail="At least one event type is required")
    return normalized
