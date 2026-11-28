"""Alert in → Action started in its Workspace → outcome recorded."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Task, TaskRun
from ...models.integration.webhook import Webhook, WebhookEvent
from ...time_utils import utc_now
from ..webhook_secret import resolve_webhook_secret
from ..webhook_service_user import (
    STATE_WEBHOOK_SERVICE_USER_NOT_CONFIGURED,
    WebhookServiceUserConflictError,
    ensure_webhook_service_user,
)
from .admission import (
    OUTCOME_GROUPED,
    OUTCOME_STARTED,
    AlertDecision,
    decide,
    target_required,
)
from .alert_events import (
    _bounded_payload,
    _deliver_run_event,
    _emit_alert_event,
    _event,
    _parse,
    _record_alert_linked,
    _words,
)
from .call_guard import (
    OUTCOME_REJECTED_REPLAY,
    OUTCOME_REJECTED_SIGNATURE,
    claim_delivery_key,
    record_rejection,
    release_delivery_key,
)
from .intake_trigger import is_intake_task, trigger_intake_sync
from .normalize import RUN_EVENT_SOURCE_TYPES, NormalizedAlert, normalize_alert
from .occurrence import KIND_SAME_OCCURRENCE
from .signature import CallCheck, verify_call
from .targets import workspace_alert_targets

logger = logging.getLogger(__name__)

STATE_ACTION_NOT_QUEUED = "action_not_queued"

# Senders that cannot sign a timestamp; their identical-body repeat may be a resend, never for HMAC-timestamped.
_UNTIMESTAMPED_METHODS = frozenset({"bearer", "hmac", "header"})
_RESENDING_SOURCE_TYPES = frozenset({"alertmanager"})


def _may_be_resend(webhook: Webhook, signature_method: str | None, delivery_key: str) -> bool:
    return ((webhook.source_type or "") in _RESENDING_SOURCE_TYPES and signature_method in _UNTIMESTAMPED_METHODS
            and delivery_key.startswith("body:"))


def _resend_grouped(decision: AlertDecision) -> bool:
    return (decision.outcome == OUTCOME_GROUPED and decision.dedup is not None
            and decision.dedup.kind == KIND_SAME_OCCURRENCE)


def _scheduler(scheduler: Any | None) -> Any:
    if scheduler is not None:
        return scheduler
    from ...runtime_lifecycle import get_task_scheduler

    return get_task_scheduler()


async def verify_signature(db: AsyncSession, webhook: Webhook, body: bytes,
                           headers: Mapping[str, str] | None) -> CallCheck:
    secret = await resolve_webhook_secret(db, webhook, purpose="inbound_webhook.verify_signature")
    check = verify_call(headers or {}, body, secret, accept_untimestamped=bool(webhook.accept_untimestamped))
    if not check.ok:
        await record_rejection(db, webhook, outcome=OUTCOME_REJECTED_SIGNATURE, reason=check.reason)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return check


async def _check_call(
    db: AsyncSession, webhook: Webhook, body: bytes, headers: Mapping[str, str] | None, *, verified: bool,
    delivery_key: str | None, signature: CallCheck | None,
) -> tuple[str | None, str | None, bool]:
    signature_method = "connector" if verified else None
    if not verified:
        # The signature is checked first, so an unauthenticated caller cannot even tell a paused webhook.
        check = signature or await verify_signature(db, webhook, body, headers)
        signature_method, delivery_key = check.method, check.delivery_key
    if not webhook.is_active:
        raise HTTPException(status_code=403, detail="Webhook is paused")
    resend = False
    if delivery_key and not await claim_delivery_key(db, webhook.id, delivery_key):
        if not _may_be_resend(webhook, signature_method, delivery_key):
            await record_rejection(db, webhook, outcome=OUTCOME_REJECTED_REPLAY, reason=OUTCOME_REJECTED_REPLAY)
            raise HTTPException(status_code=409, detail="Replayed webhook call")
        resend = True
    return signature_method, delivery_key, resend


async def _decide_locked(
    db: AsyncSession, webhook: Webhook, alert: NormalizedAlert, *, is_test: bool
) -> tuple[Task | None, AlertDecision]:
    # Decide-and-record under the webhook's row lock (PostgreSQL), so concurrent calls cannot overrun the limit.
    await db.execute(select(Webhook.id).where(Webhook.id == webhook.id).with_for_update())
    task = await db.get(Task, webhook.task_id) if webhook.task_id else None
    # Opt-in per Action: only an Action that requires a target reads the Workspace's alert targets.
    required = target_required(task)
    targets, target_errors = await workspace_alert_targets(db, webhook.project_id) if required else (None, [])
    decision = await decide(db, webhook, task, alert, is_test=is_test, targets=targets, target_required=required,
                            target_errors=target_errors)
    return task, decision


async def _record_decision(
    db: AsyncSession, webhook: Webhook, decision: AlertDecision, alert: NormalizedAlert, data: Any, *,
    is_test: bool, signature_method: str | None,
) -> tuple[WebhookEvent, dict[str, Any]]:
    event = _event(webhook, outcome=decision.outcome, alert=alert, payload=data, is_test=is_test,
                   words=_words(decision))
    if decision.outcome == OUTCOME_GROUPED:
        event.task_run_id = decision.grouped_with_run_id
    db.add(event)
    if decision.outcome == OUTCOME_GROUPED:
        await db.flush()
        await _record_alert_linked(db, event, decision)
    await db.commit()
    result = {"accepted": True, "event_id": event.id, "outcome": decision.outcome, "message": event.parsed_message,
              "task_run_id": event.task_run_id, "signature": signature_method}
    if decision.dedup is not None and decision.outcome in (OUTCOME_GROUPED, OUTCOME_STARTED):
        result["dedup"] = decision.dedup.kind
    return event, result


async def _start_action(
    db: AsyncSession, webhook: Webhook, task: Any, alert: NormalizedAlert, decision: AlertDecision,
    event: WebhookEvent, data: Any, result: dict[str, Any], *, is_test: bool, delivery_key: str | None,
    scheduler: Any | None,
) -> dict[str, Any]:
    async def _fail(code: str, status: int, detail: str | dict[str, Any]) -> HTTPException:
        event.outcome, event.status = "failed", "failed"
        event.error = code
        event.parsed_message = "The action could not be started"
        event.processed_at = utc_now()
        await db.commit()
        if delivery_key:
            await release_delivery_key(db, webhook.id, delivery_key)
        return HTTPException(status_code=status, detail=detail)

    try:
        principal = await ensure_webhook_service_user(db, webhook)
        await db.commit()
    except WebhookServiceUserConflictError:
        raise await _fail(STATE_WEBHOOK_SERVICE_USER_NOT_CONFIGURED, 409,
                          STATE_WEBHOOK_SERVICE_USER_NOT_CONFIGURED) from None

    run_input = {"inbound_alert": {
        "webhook_id": webhook.id,
        "event_id": event.id,
        "is_test": is_test,
        "alert": alert.as_dict(),
        "payload": _bounded_payload(data),
        "target": decision.target.as_context() if decision.target is not None else None,
        "dedup": decision.dedup.as_dict() if decision.dedup is not None else None,
    }}
    from ...scheduler.dispatch.backend import TASK_WORKSPACE_REQUIRED, TaskNotRunnableError

    try:
        queued = await _scheduler(scheduler).run_task_now(
            task.id, trigger_type="webhook", trigger_id=webhook.id, started_by=principal.id, run_input=run_input
        )
    except TaskNotRunnableError as refused:
        if refused.reason != TASK_WORKSPACE_REQUIRED:
            raise await _fail(STATE_ACTION_NOT_QUEUED, 503, "The action could not be queued; try again") from None
        from ..run_admission.denials import workspace_required_detail

        raise await _fail(TASK_WORKSPACE_REQUIRED, 409, workspace_required_detail(str(refused))) from None
    except Exception:
        logger.warning("inbound_alert.queue_failed webhook_id=%s", webhook.id, exc_info=True)
        raise await _fail(STATE_ACTION_NOT_QUEUED, 503, "The action could not be queued; try again") from None
    event.task_run_id = str(queued.get("task_run_id") or "") or None
    await db.commit()
    if not is_test:
        # A test alert posts nothing anywhere, outbound webhooks included.
        await _emit_alert_event(db, webhook, event, alert)
    result.update({"task_run_id": event.task_run_id, "workspace_id": webhook.project_id, "action_id": task.id})
    return result


async def receive_alert(
    db: AsyncSession,
    *,
    webhook: Webhook,
    body: bytes,
    headers: Mapping[str, str] | None = None,
    payload: Any = None,
    is_test: bool = False,
    verified: bool = False,
    delivery_key: str | None = None,
    scheduler: Any | None = None,
    signature: CallCheck | None = None,
) -> dict[str, Any]:
    signature_method, delivery_key, resend = await _check_call(
        db, webhook, body, headers, verified=verified, delivery_key=delivery_key, signature=signature
    )
    data = payload if payload is not None else _parse(body)
    bound = await db.get(Task, webhook.task_id) if webhook.task_id else None
    if is_intake_task(bound):  # a Work intake's sync, never an agent turn (``intake_trigger``)
        return await trigger_intake_sync(db, webhook, bound, _scheduler(scheduler), is_test=is_test,
                                         signature_method=signature_method)
    if (webhook.source_type or "") in RUN_EVENT_SOURCE_TYPES:
        return await _deliver_run_event(db, webhook, data, headers or {}, is_test=is_test,
                                        signature_method=signature_method)
    if (webhook.source_type or "") == "jira_change" and isinstance(data, dict) and not is_test:
        # A polled Jira change also reaches workflow runs that watch the issue's Work state (S4b); a test alert never.
        from ..workflow_runs.watch import deliver_jira_change

        await deliver_jira_change(db, data, project_id=webhook.project_id)
    alert = normalize_alert(webhook.source_type or "generic", data)
    task, decision = await _decide_locked(db, webhook, alert, is_test=is_test)
    if resend and not _resend_grouped(decision):
        # Only a resend of an occurrence already analysed is answered; anything else stays a replay.
        await record_rejection(db, webhook, outcome=OUTCOME_REJECTED_REPLAY, reason=OUTCOME_REJECTED_REPLAY)
        raise HTTPException(status_code=409, detail="Replayed webhook call")
    event, result = await _record_decision(db, webhook, decision, alert, data, is_test=is_test,
                                           signature_method=signature_method)
    if not decision.starts:
        if decision.reason:
            result["reason"] = decision.reason
        return result
    return await _start_action(db, webhook, task, alert, decision, event, data, result, is_test=is_test,
                               delivery_key=delivery_key, scheduler=scheduler)


async def run_of_event(db: AsyncSession, event: WebhookEvent) -> TaskRun | None:
    if not event.task_run_id:
        return None
    return (await db.execute(select(TaskRun).where(TaskRun.id == event.task_run_id))).scalar_one_or_none()


__all__ = ["receive_alert", "run_of_event"]
