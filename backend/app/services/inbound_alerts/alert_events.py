"""The recorded side of an inbound call (``trigger``): the bounded event row, its words, the run-event delivery
and the notices after a start."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration.webhook import Webhook, WebhookEvent
from ...time_utils import utc_now
from .admission import (
    OUTCOME_GROUPED,
    OUTCOME_NEEDS_SETUP,
    OUTCOME_SKIPPED_FILTERED,
    OUTCOME_SKIPPED_RATE_LIMIT,
    OUTCOME_SKIPPED_RESOLVED,
    OUTCOME_STARTED,
    SETUP_MESSAGES,
    AlertDecision,
)
from .normalize import NormalizedAlert
from .occurrence import KIND_RECURRENCE, KIND_REOPEN, KIND_SAME_OCCURRENCE

# The trigger's logger, so these records keep the name they were always logged under.
logger = logging.getLogger("app.services.inbound_alerts.trigger")

MAX_STORED_PAYLOAD_BYTES = 64 * 1024

_OUTCOME_WORDS = {
    OUTCOME_STARTED: "Analysis started",
    OUTCOME_GROUPED: "Grouped with an earlier alert",
    OUTCOME_SKIPPED_RESOLVED: "Resolved alerts don't start an analysis",
    OUTCOME_SKIPPED_FILTERED: "Filtered out by severity",
    OUTCOME_SKIPPED_RATE_LIMIT: "Skipped: the hourly limit was reached",
}
_DEDUP_WORDS = {
    KIND_SAME_OCCURRENCE: "Grouped: this alert occurrence is already analysed",
    KIND_RECURRENCE: "Grouped: the alert fired again while its analysis is open",
    KIND_REOPEN: "Analysis started again: the alert came back after its analysis ended",
}


def _bounded_payload(payload: Any) -> Any:
    try:
        encoded = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"unreadable": True}
    if len(encoded.encode()) <= MAX_STORED_PAYLOAD_BYTES:
        return payload
    return {"truncated": True, "preview": encoded[:4000]}


def _parse(body: bytes) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"message": body.decode("utf-8", "replace")[:2000]}


def _event(webhook: Webhook, *, outcome: str, alert: NormalizedAlert | None, payload: Any, is_test: bool,
           words: str) -> WebhookEvent:
    return WebhookEvent(
        id=str(uuid.uuid4()),
        webhook_id=webhook.id,
        status="processing" if outcome == OUTCOME_STARTED else "skipped",
        outcome=outcome,
        raw_payload=_bounded_payload(payload) if payload is not None else None,
        parsed_message=words,
        fingerprint=alert.fingerprint if alert else None,
        alert_title=alert.title if alert else None,
        is_test=is_test,
        processed_at=None if outcome == OUTCOME_STARTED else utc_now(),
    )


def _words(decision: AlertDecision) -> str:
    if decision.outcome == OUTCOME_NEEDS_SETUP:
        return SETUP_MESSAGES.get(decision.reason, "")
    dedup = decision.dedup
    words = _DEDUP_WORDS.get(dedup.kind, "") if dedup is not None and decision.outcome in (
        OUTCOME_GROUPED, OUTCOME_STARTED) else ""
    words = words or _OUTCOME_WORDS.get(decision.outcome, "")
    return f"{words} · severity rose" if dedup is not None and dedup.escalated and words else words


async def _record_alert_linked(db: AsyncSession, event: WebhookEvent, decision: AlertDecision) -> None:
    """The grouped alert on the workflow run it joined; escalation is only recorded, not acted on."""
    dedup = decision.dedup
    if dedup is None or not dedup.linked_workflow_run_id:
        return
    from ...models import WorkflowRun
    from ..workflow_runs.records import record_event

    run = await db.get(WorkflowRun, dedup.linked_workflow_run_id)
    if run is None:
        return
    record_event(db, run, "alert_linked", detail={
        "event_id": event.id,
        "occurrences": [list(pair) for pair in dedup.new_occurrences or dedup.occurrences],
        "escalated": dedup.escalated,
        "kind": dedup.kind,
    })


async def _deliver_run_event(db: AsyncSession, webhook: Webhook, data: Any, headers: Mapping[str, str], *,
                             is_test: bool, signature_method: str | None) -> dict[str, Any]:
    """An SCM or CI event: hand it to the workflow runs that watch its target; no Action starts."""
    from ..workflow_runs.watch import deliver_event
    from ..workflow_runs.watch_events import ci_event, scm_event

    reader = scm_event if webhook.source_type == "scm_pull_request" else ci_event
    event = reader(data, headers)
    moved = [] if event is None or is_test else await deliver_event(db, event, source=webhook.source_type,
                                                                     project_id=webhook.project_id)
    words = (f"Moved {len(moved)} workflow run(s)" if moved else
             "No workflow run waits for this event" if event is not None else "Not an event workflow runs watch")
    row = WebhookEvent(id=str(uuid.uuid4()), webhook_id=webhook.id, status="processed", outcome="run_event",
                       raw_payload=_bounded_payload(data), parsed_message=words,
                       alert_title=event.condition if event is not None else None, is_test=is_test,
                       processed_at=utc_now())
    db.add(row)
    await db.commit()
    bot = None
    if webhook.source_type == "scm_pull_request":  # an opened or pushed pull request starts the review bot's run
        from ..pr_review_bot.webhook import on_scm_webhook

        # After the watching runs' moves are committed: the bot's own failure rolls back only its own start.
        bot = await on_scm_webhook(db, webhook, data, headers or {}, is_test=is_test)
        if bot:
            row.parsed_message = words = f"{words} · review bot: {bot.get('outcome')}"
            await db.commit()
    return {"accepted": True, "event_id": row.id, "outcome": "run_event", "message": words,
            "workflow_runs": moved, "signature": signature_method, **({"review_bot": bot} if bot else {})}


async def _emit_alert_event(db: AsyncSession, webhook: Webhook, event: WebhookEvent, alert: NormalizedAlert) -> None:
    from ..outbound_webhook import emit_outbound_webhook_event

    try:
        await emit_outbound_webhook_event(
            db,
            event_type="alert.triggered",
            project_id=webhook.project_id,
            payload={"webhook_id": webhook.id, "event_id": event.id, "task_run_id": event.task_run_id,
                     "source_type": webhook.source_type, "alert": alert.as_dict()},
        )
        await db.commit()
    except Exception:
        logger.warning("inbound_alert.outbound_emit_failed event_id=%s", event.id, exc_info=True)
        await db.rollback()
