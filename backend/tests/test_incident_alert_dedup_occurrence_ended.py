"""Ended runs regroup, reopen or start anew, and grouping stays per alert, per webhook and off for test alerts."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import TaskRun
from app.models.integration.webhook import Webhook, WebhookEvent
from app.services.inbound_alerts.samples import sample_payload
from app.time_utils import utc_now
from tests.s5_alert_dedup_support import A_AGAIN, A, am, bind_workflow_run, deliver, task_runs
from tests.test_inbound_alert_starts_action import _setup


async def end_task_run(db, task_run_id: str, *, minutes_ago: int, status: str = "success") -> None:
    run = await db.get(TaskRun, task_run_id)
    run.status, run.completed_at = status, utc_now() - timedelta(minutes=minutes_ago)
    await db.commit()


@pytest.mark.asyncio
async def test_the_same_occurrence_after_the_run_ended_is_grouped_without_re_analysis(db):
    admin, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    await bind_workflow_run(db, first["task_run_id"], admin.id, status="completed", minutes_ago=600)

    repeat = await deliver(db, created["id"], am(A))

    assert (repeat["outcome"], repeat["dedup"]) == ("grouped", "same_occurrence")
    assert await task_runs(db, task.id) == 1


@pytest.mark.asyncio
async def test_a_severity_rise_after_the_run_ended_reopens(db):
    admin, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A, severity="warning"))
    workflow = await bind_workflow_run(db, first["task_run_id"], admin.id, status="completed", minutes_ago=600)

    risen = await deliver(db, created["id"], am(A, severity="critical"))

    assert (risen["outcome"], risen["dedup"]) == ("started", "reopen")
    dedup = (await db.get(TaskRun, risen["task_run_id"])).input_["inbound_alert"]["dedup"]
    assert dedup["escalated"] is True
    assert dedup["reopens"] == {"task_run_id": first["task_run_id"], "workflow_run_id": workflow.id}
    assert await task_runs(db, task.id) == 2


@pytest.mark.asyncio
async def test_a_new_occurrence_shortly_after_the_run_ended_reopens(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    await end_task_run(db, first["task_run_id"], minutes_ago=10)

    back = await deliver(db, created["id"], am(A_AGAIN))

    assert (back["outcome"], back["dedup"]) == ("started", "reopen")
    assert back["message"] == "Analysis started again: the alert came back after its analysis ended"
    dedup = (await db.get(TaskRun, back["task_run_id"])).input_["inbound_alert"]["dedup"]
    assert dedup["reopens"] == {"task_run_id": first["task_run_id"], "workflow_run_id": None}
    assert dedup["occurrences"] == [list(A_AGAIN)]
    assert await task_runs(db, task.id) == 2


@pytest.mark.asyncio
async def test_a_new_occurrence_long_after_the_run_ended_is_new(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    await end_task_run(db, first["task_run_id"], minutes_ago=61)

    back = await deliver(db, created["id"], am(A_AGAIN))

    assert (back["outcome"], back["dedup"]) == ("started", "new")
    assert "reopens" not in (await db.get(TaskRun, back["task_run_id"])).input_["inbound_alert"]["dedup"]
    assert await task_runs(db, task.id) == 2


@pytest.mark.asyncio
async def test_a_failed_run_is_ended_too(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A))
    await end_task_run(db, first["task_run_id"], minutes_ago=5, status="error")

    back = await deliver(db, created["id"], am(A_AGAIN))

    assert (back["outcome"], back["dedup"]) == ("started", "reopen")


@pytest.mark.asyncio
async def test_a_different_alert_on_the_same_webhook_is_new(db):
    _, _, task, created = await _setup(db)
    await deliver(db, created["id"], am(A))

    other = await deliver(db, created["id"], am(("fp-z", "2026-10-15T10:00:00Z"), service="payments"))

    assert (other["outcome"], other["dedup"]) == ("started", "new")
    assert await task_runs(db, task.id) == 2


@pytest.mark.asyncio
async def test_dedup_is_per_webhook(db):
    _, _, task, created = await _setup(db)
    _, _, other_task, other = await _setup(db)
    await deliver(db, created["id"], am(A))

    elsewhere = await deliver(db, other["id"], am(A))

    assert (elsewhere["outcome"], elsewhere["dedup"]) == ("started", "new")


@pytest.mark.asyncio
async def test_test_alerts_are_never_grouped_and_never_group_real_ones(db):
    _, _, task, created = await _setup(db)
    first = await deliver(db, created["id"], am(A), is_test=True)
    second = await deliver(db, created["id"], am(A), is_test=True)
    real = await deliver(db, created["id"], am(A))

    assert [first["outcome"], second["outcome"], real["outcome"]] == ["started"] * 3
    assert real["dedup"] == "new"


@pytest.mark.asyncio
async def test_a_resolved_alert_keeps_its_occurrence_on_the_event(db):
    _, _, _, created = await _setup(db)
    resolved = await deliver(db, created["id"], am(A, status="resolved"))

    assert resolved["outcome"] == "skipped_resolved"
    event = await db.get(WebhookEvent, resolved["event_id"])
    assert [(item["fingerprint"], item["startsAt"]) for item in event.raw_payload["alerts"]] == [A]


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", ["datadog", "pagerduty", "sentry", "generic"])
async def test_sources_without_occurrences_keep_the_time_grouping(db, source_type):
    _, _, task, created = await _setup(db)
    hook = await db.get(Webhook, created["id"])
    hook.source_type = source_type
    await db.commit()
    payload = sample_payload(source_type, "firing_error_rate")

    first = await deliver(db, created["id"], payload)
    await end_task_run(db, first["task_run_id"], minutes_ago=600)  # ended: the time window alone decides
    again = await deliver(db, created["id"], payload)

    assert (first["outcome"], again["outcome"], again["task_run_id"]) == ("started", "grouped",
                                                                           first["task_run_id"])
    assert "dedup" not in again
    hook.group_window_minutes = 0
    await db.commit()
    third = await deliver(db, created["id"], payload)
    assert third["outcome"] == "started", "window 0 never groups these sources"
    assert await task_runs(db, task.id) == 2
