"""Shared queue-only scheduler, alert payloads and run helpers for the S5.2 alert dedup tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.models import TaskRun, WorkflowRun
from app.models.integration.webhook import Webhook
from app.models.runtime.workflow_run import WorkflowRunSession
from app.services.inbound_alerts import trigger
from app.time_utils import utc_now


class QueueOnly:
    def __init__(self, db, *, assign_run: bool = True):
        self.db, self.assign_run, self.runs = db, assign_run, []

    async def run_task_now(self, task_id, *, trigger_type, trigger_id, started_by, run_input):
        run = TaskRun(id=str(uuid.uuid4()), task_id=task_id, trigger_type=trigger_type, trigger_id=trigger_id,
                      status="queued", started_by=started_by, input_=run_input)
        self.db.add(run)
        await self.db.commit()
        self.runs.append(run)
        return {"task_run_id": run.id if self.assign_run else None}


def am(*alerts: tuple[str, str], severity: str = "warning", service: str = "checkout", namespace: str = "shop",
       status: str = "firing") -> dict:
    common = {"alertname": "CheckoutErrors", "service": service, "namespace": namespace}
    return {
        "version": "4", "status": status, "receiver": "octryx", "groupKey": "{}:{alertname=\"CheckoutErrors\"}",
        "commonLabels": common,
        "alerts": [{"status": status, "fingerprint": fingerprint, "startsAt": starts,
                    "labels": {**common, "severity": severity, "pod": f"checkout-{fingerprint}"},
                    "annotations": {"summary": "Errors"}} for fingerprint, starts in alerts],
    }


async def deliver(db, webhook_id: str, payload: dict, scheduler=None, *, is_test: bool = False) -> dict:
    webhook = await db.get(Webhook, webhook_id)
    return await trigger.receive_alert(db, webhook=webhook, body=b"{}", payload=payload, verified=True,
                                       delivery_key=f"id:{uuid.uuid4().hex}", is_test=is_test,
                                       scheduler=scheduler or QueueOnly(db))


async def bind_workflow_run(db, task_run_id: str, owner_id: str, *, status: str = "waiting",
                            minutes_ago: int | None = None) -> WorkflowRun:
    run = await db.get(TaskRun, task_run_id)
    run.session_id = run.session_id or str(uuid.uuid4())
    workflow = WorkflowRun(workflow_kind="phased", workflow_key="incident-analysis", title="Incident",
                           requested_by=owner_id, status=status,
                           completed_at=utc_now() - timedelta(minutes=minutes_ago) if minutes_ago else None)
    db.add(workflow)
    await db.flush()
    db.add(WorkflowRunSession(run_id=workflow.id, session_id=run.session_id))
    run.status = "success"  # the Action's turn ended; the workflow run decides whether it is open
    run.completed_at = utc_now() - timedelta(minutes=90)
    await db.commit()
    return workflow


async def task_runs(db, task_id: str) -> int:
    return int((await db.execute(select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id)))
               .scalar_one())


A = ("fp-a", "2026-10-15T10:00:00Z")


A_AGAIN = ("fp-a", "2026-10-15T12:00:00Z")


B = ("fp-b", "2026-10-15T10:02:00Z")
