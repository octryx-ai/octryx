"""Dedup by key and occurrence through ``receive_alert``: one open run per (service, fingerprint), linked, reopened or
new."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import TaskRun
from app.models.integration.webhook import WebhookEvent
from app.models.runtime.workflow_run import WorkflowRunEvent
from app.services.inbound_alerts.occurrence import dedup_key
from tests.s5_alert_dedup_support import A_AGAIN, A, B, QueueOnly, am, bind_workflow_run, deliver, task_runs
from tests.test_inbound_alert_starts_action import _setup


async def linked_events(db, workflow_run_id: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == workflow_run_id, WorkflowRunEvent.kind == "alert_linked"))).scalars())


def test_dedup_key_is_sha256_of_service_and_fingerprint():
    key = dedup_key("checkout", "f" * 64)
    assert len(key) == 64 and int(key, 16) >= 0
    assert key == dedup_key("checkout", "f" * 64)
    assert key != dedup_key("payments", "f" * 64)
    assert key != dedup_key("checkout", "e" * 64)


@pytest.mark.asyncio
async def test_the_same_occurrence_while_the_run_is_queued_is_grouped_with_it(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    assert (first["outcome"], first["dedup"]) == ("started", "new")
    queued = await db.get(TaskRun, first["task_run_id"])
    assert queued.status == "queued"
    assert queued.input_["inbound_alert"]["dedup"]["occurrences"] == [list(A)]
    assert queued.input_["inbound_alert"]["dedup"]["key"] == dedup_key("checkout", queued.input_[
        "inbound_alert"]["alert"]["fingerprint"])

    again = await deliver(db, created["id"], am(A))

    assert (again["outcome"], again["dedup"], again["task_run_id"]) == ("grouped", "same_occurrence", queued.id)
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_started_event_whose_run_is_not_queued_yet_counts_as_open(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A), QueueOnly(db, assign_run=False))
    event = await db.get(WebhookEvent, first["event_id"])
    assert (event.outcome, event.task_run_id) == ("started", None)

    again = await deliver(db, created["id"], am(A))

    assert (again["outcome"], again["dedup"]) == ("grouped", "same_occurrence")
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_group_that_gains_an_alert_is_the_same_occurrence_and_is_linked_on_the_workflow_run(db):
    admin, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    workflow = await bind_workflow_run(db, first["task_run_id"], admin.id, status="waiting")

    grown = await deliver(db, created["id"], am(A, B))

    assert (grown["outcome"], grown["dedup"], grown["task_run_id"]) == ("grouped", "same_occurrence",
                                                                         first["task_run_id"])
    [linked] = await linked_events(db, workflow.id)
    assert linked.detail == {"event_id": grown["event_id"], "occurrences": [list(B)], "escalated": False,
                             "kind": "same_occurrence"}
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_severity_rise_on_an_open_run_is_grouped_and_recorded_as_escalated(db):
    admin, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A, severity="warning"))
    workflow = await bind_workflow_run(db, first["task_run_id"], admin.id, status="running")

    risen = await deliver(db, created["id"], am(A, severity="critical"))

    assert (risen["outcome"], risen["dedup"]) == ("grouped", "same_occurrence")
    assert risen["message"].endswith("· severity rose")
    [linked] = await linked_events(db, workflow.id)
    assert linked.detail["escalated"] is True
    again = await deliver(db, created["id"], am(A, severity="critical"))
    assert "severity rose" not in again["message"], "the rise is recorded once, not on every later repeat"
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_new_occurrence_while_the_run_is_open_is_a_recurrence_on_that_run(db):
    admin, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    workflow = await bind_workflow_run(db, first["task_run_id"], admin.id, status="paused")

    refired = await deliver(db, created["id"], am(A_AGAIN))

    assert (refired["outcome"], refired["dedup"], refired["task_run_id"]) == ("grouped", "recurrence",
                                                                               first["task_run_id"])
    [linked] = await linked_events(db, workflow.id)
    assert linked.detail["occurrences"] == [list(A_AGAIN)]
    assert await task_runs(db, task.id) == 1
