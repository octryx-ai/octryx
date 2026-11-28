"""How a finished task run ends: its failure decision and retry, its output delivery, webhook and session tree."""

from __future__ import annotations

import logging

from sqlalchemy import select

from ...services.circuit_breaker import escalate_failed_task_run_decision
from ...services.outbound_webhook import emit_outbound_webhook_event
from ...time_utils import utc_now
from ..output import deliver_task_output_channel as _deliver_task_output_channel
from .inbound_alert_turn import (
    alert_retry_identity,
    finalize_alert_event,
    suppress_delivery,
)
from .task_run_kinds import _Outcome

logger = logging.getLogger(__name__)


async def _handle_failure(db, scheduler, task, task_run, queue_entry, outcome: _Outcome, *, trigger_type: str,
                          trigger_id: str | None) -> None:
    failure_message = task_run.error or str((task_run.output or {}).get("task_error") or "task_failed")
    failed_entry, failure_decision = await escalate_failed_task_run_decision(
        db,
        task_id=task.id,
        task_run_id=task_run.id,
        error=failure_message,
        trigger_id=trigger_id if trigger_type == "retry" else None,
        admission_refused=outcome.admission_refused,
        reply_contract_violation=outcome.reply_contract_violation,
        runtime_stopped=outcome.runtime_stopped,
        content_blocked=outcome.content_blocked,
    )
    task_run.output = {**dict(task_run.output or {}), "failure_decision": failure_decision.as_dict()}
    if queue_entry:
        queue_entry.status = failure_decision.queue_status
        queue_entry.next_retry_at = failed_entry.next_retry_at
        queue_entry.last_error = failure_decision.failure_message
    await db.commit()
    retry_scheduled = bool(failure_decision.retryable and failure_decision.retry_delay_seconds is not None)
    if outcome.action_run_id:
        await _pause_action_run(db, task_run, outcome, failure_message, retry_scheduled=retry_scheduled)
    if retry_scheduled:
        scheduler._schedule_failed_task_retry(
            task_id=task.id,
            failed_task_run_id=failed_entry.id,
            delay_seconds=failure_decision.retry_delay_seconds,
            # An alert-started run is retried as the same automation identity with the same alert.
            **alert_retry_identity(task_run),
        )


async def _pause_action_run(db, task_run, outcome: _Outcome, failure_message: str, *, retry_scheduled: bool) -> None:
    # The run this turn ran in does not stay ``running`` silently; a retry continues it.
    from ...services.workflow_runs.automation import pause_failed_action_run

    try:
        paused = await pause_failed_action_run(
            db, outcome.action_run_id, content_blocked=outcome.content_blocked,
            code=task_run.error or failure_message, task_run=task_run,
            retry_scheduled=retry_scheduled,
        )
        if paused is not None:
            task_run.output = {
                **dict(task_run.output or {}),
                "workflow_run": {"run_id": paused.id, "status": paused.status, "pause_reason": paused.pause_reason},
            }
        await db.commit()
    except Exception:
        logger.exception("[scheduler] Task %s could not pause its workflow run %s",
                         task_run.task_id, outcome.action_run_id)
        await db.rollback()


async def _deliver_output(db, task, task_run) -> None:
    # A test alert's run posts nothing.
    delivery_result = None if suppress_delivery(task_run) else await _deliver_task_output_channel(db, task, task_run)
    await finalize_alert_event(db, task_run, delivery_result)
    if delivery_result is not None:
        task_run.output = {**dict(task_run.output or {}), "channel_delivery": delivery_result}
        await db.commit()


async def _emit_webhook(db, task, task_run, *, trigger_type: str):
    # The enqueue below is a single DB insert into the outbound-webhook delivery queue (OutboundWebhookDelivery); a
    # separate worker drains that queue with its own bounded retry / dead-letter policy, so a local retry here would
    # be pointless. An enqueue failure is recorded on the task_run.output trail and in a structured log instead.
    # A test alert's run posts nothing anywhere, outbound webhooks included.
    if suppress_delivery(task_run):
        return task_run
    from ...models import TaskRun

    webhook_event_type = "task.failed" if task_run.status == "error" else "task.completed"
    try:
        await emit_outbound_webhook_event(
            db,
            event_type=webhook_event_type,
            project_id=task.project_id,
            payload={
                "task_id": task.id,
                "task_name": task.name,
                "task_run_id": task_run.id,
                "status": task_run.status,
                "trigger_type": trigger_type,
                "session_id": task_run.session_id,
                "error": task_run.error,
                "output": task_run.output if isinstance(task_run.output, dict) else {},
            },
        )
        await db.commit()
    except Exception as webhook_exc:
        # Do NOT swallow: record the enqueue failure on the task_run so it is queryable, and log it with
        # structure. The task_run itself stays finalized deterministically (success/error unchanged).
        logger.exception(
            "scheduler.task_webhook.enqueue_failed task_run_id=%s event_type=%s error=%s",
            task_run.id,
            webhook_event_type,
            str(webhook_exc),
        )
        await db.rollback()
        refreshed = (await db.execute(select(TaskRun).where(TaskRun.id == task_run.id))).scalar_one_or_none()
        if refreshed is not None:
            task_run = refreshed
        task_run.output = {**dict(task_run.output or {}), "webhook_enqueue": {
            "status": "failed",
            "event_type": webhook_event_type,
            "error": str(webhook_exc),
            "failed_at": utc_now().isoformat(),
        }}
        await db.commit()
    return task_run


async def _finalize_session_tree(db, scheduler, task, task_run) -> None:
    from ...services.workflow_runs.automation import action_run_config

    await scheduler._finalize_task_session_tree(
        db,
        task_run.session_id,
        preserve_phase_root=action_run_config(task) is not None,
        status="error" if task_run.status == "error" else "completed",
        stop_reason="task_failed" if task_run.status == "error" else "task_completed",
    )
