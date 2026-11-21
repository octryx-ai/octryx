"""An inbound webhook bound to a Work intake's sync task triggers that intake's sync.

A source that can push ("a ticket changed") should not wait for the next schedule, and must not start an agent turn
either: the call only queues the intake's own deterministic sync task (``run_task_now``, ``trigger_type`` ``webhook``),
which reads the API itself through the intake's scope. The webhook's payload never reaches the run (third-party text,
nothing to act on). A disabled intake is answered ``intake_not_enabled`` and nothing runs: it is enabled only after a
preview, and a webhook must not bypass that. Signature, replay and pause checks ran before (``trigger.receive_alert``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Task, WorkItemSyncConfig
from ...models.integration.webhook import Webhook, WebhookEvent
from ...time_utils import utc_now

OUTCOME_INTAKE_SYNC = "intake_sync"
OUTCOME_INTAKE_NOT_ENABLED = "intake_not_enabled"


def is_intake_task(task: Task | None) -> bool:
    from ..secure_work.intake.registry import sync_task_types

    return task is not None and task.task_type in sync_task_types()


async def trigger_intake_sync(db: AsyncSession, webhook: Webhook, task: Task, scheduler: Any, *, is_test: bool,
                              signature_method: str | None) -> dict[str, Any]:
    row = await db.get(WorkItemSyncConfig, str((task.config or {}).get("sync_config_id") or ""))
    enabled = row is not None and bool(row.is_active) and row.project_id == webhook.project_id
    outcome = OUTCOME_INTAKE_SYNC if enabled and not is_test else OUTCOME_INTAKE_NOT_ENABLED if not enabled \
        else "test"
    event = WebhookEvent(id=str(uuid.uuid4()), webhook_id=webhook.id, status="processed", outcome=outcome,
                         raw_payload=None, parsed_message={
                             OUTCOME_INTAKE_SYNC: "Intake sync started",
                             OUTCOME_INTAKE_NOT_ENABLED: "The intake is not enabled; nothing ran",
                         }.get(outcome, "Test call: the intake sync was not started"),
                         is_test=is_test, processed_at=utc_now())
    db.add(event)
    await db.commit()
    result: dict[str, Any] = {"accepted": True, "event_id": event.id, "outcome": outcome,
                              "message": event.parsed_message, "signature": signature_method, "task_run_id": None}
    if outcome != OUTCOME_INTAKE_SYNC:
        return result
    queued = await scheduler.run_task_now(task.id, trigger_type="webhook", trigger_id=webhook.id,
                                          started_by=webhook.owner_id, allow_inactive=True)
    event.task_run_id = str(queued.get("task_run_id") or "") or None
    await db.commit()
    return {**result, "task_run_id": event.task_run_id, "intake_id": row.id}


__all__ = ["OUTCOME_INTAKE_NOT_ENABLED", "OUTCOME_INTAKE_SYNC", "is_intake_task", "trigger_intake_sync"]
