"""Contract: scheduler expressions are previewed and validated with the registration engine."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from app import runtime_lifecycle
from app.models import Task, User
from app.models.project.scheduler import Scheduler
from app.scheduler.coordination.fingerprint import SCHEDULER_KIND, ScheduleRecord
from app.scheduler.dispatch import cron_schedule
from app.scheduler.dispatch import registration as registration_module
from app.scheduler.dispatch.registration import SchedulerRegistrationMixin
from app.services.auth.tokens import create_access_token, hash_password

pytestmark = pytest.mark.asyncio
PANEL = "/admin/chat/api/panel/schedulers"
ZURICH = ZoneInfo("Europe/Zurich")


async def _task(db) -> Task:
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    task = Task(dispatch_binding="task_definition", name=f"scheduled-{uuid.uuid4().hex[:6]}", owner_id=admin_id, task_type="agent_run")
    db.add(task)
    await db.commit()
    return task


async def _schedulers(db) -> int:
    await db.rollback()
    return (await db.execute(select(func.count(Scheduler.id)))).scalar_one()


@pytest.fixture
def no_job_side_effects(monkeypatch):
    def _refuse():
        raise AssertionError("the task scheduler must not be touched")

    monkeypatch.setattr(runtime_lifecycle, "get_task_scheduler", _refuse)


@pytest.fixture
def zurich(monkeypatch):
    monkeypatch.setattr(cron_schedule, "build_cron_trigger", lambda e: CronTrigger.from_crontab(e, timezone=ZURICH))


def _at_utc(result) -> list[str]:
    return [run["at_utc"] for run in result["next_runs"]]


async def test_preview_reports_typed_results_without_writes_or_jobs(admin_client, no_job_side_effects):
    writes: set[str] = set()

    def _record(_conn, _cursor, statement, *_args):
        words = statement.split()
        if words and words[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.add(words[2] if words[0].upper() in {"INSERT", "DELETE"} else words[1])

    cases = {
        "0 9 * * mon-fri": None,
        "": "cron_required",
        "* * *": "cron_field_count",
        "61 * * * *": "cron_field_invalid",
        "0 9 * * 7": "cron_field_invalid",
        "0 9 30 2 *": "cron_never_fires",
        "0 " * 51: "cron_too_long",
    }
    event.listen(Engine, "before_cursor_execute", _record)
    try:
        replies = {expr: await admin_client.post(f"{PANEL}/preview", json={"cron_expression": expr}) for expr in cases}
    finally:
        event.remove(Engine, "before_cursor_execute", _record)
    assert writes <= {"audit_log", "users"}, writes
    for expr, code in cases.items():
        body = replies[expr].json()
        assert replies[expr].status_code == 200, replies[expr].text
        assert body["cron_expression"] == expr, "the exact input is echoed, never normalized"
        assert body["timezone"]["source"] == "process_local" and body["timezone"]["name"]
        assert body["scheduling"]["owner"] in {"this_process", "separate_worker"}
        if code is None:
            assert body["valid"] is True and body["error"] is None and len(body["next_runs"]) == 5
        else:
            assert body["valid"] is False and body["error"]["code"] == code and body["next_runs"] == [], expr
    assert replies["0 9 * * 7"].json()["error"]["field"] == "day_of_week"

    bounded = await admin_client.post(f"{PANEL}/preview", json={"cron_expression": "* * * * *", "count": 10})
    assert len(bounded.json()["next_runs"]) == 10
    for count in (0, 11):
        refused = await admin_client.post(f"{PANEL}/preview", json={"cron_expression": "* * * * *", "count": count})
        assert refused.status_code == 422


async def test_preview_and_writes_refuse_anonymous_and_non_admin(client, db):
    user = User(
        username=f"plain-{uuid.uuid4().hex[:6]}",
        email=f"plain-{uuid.uuid4().hex[:6]}@example.test",
        password_hash=hash_password("Plain-User-Pw-123"),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    body = {"cron_expression": "0 9 * * *"}
    anonymous = await client.post(f"{PANEL}/preview", json=body)
    assert anonymous.status_code == 401
    member = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    assert (await client.post(f"{PANEL}/preview", json=body, headers=member)).status_code == 403
    assert (await client.post(PANEL, json={**body, "name": "x", "task_id": "x"}, headers=member)).status_code == 403


async def test_scheduling_scope_comes_from_the_background_worker_toggle(monkeypatch):
    monkeypatch.setenv("OCTRYX_DISABLE_BACKGROUND_WORKERS", "1")
    delegated = await cron_schedule.preview_schedule("0 9 * * *")
    assert delegated["scheduling"]["owner"] == "separate_worker"
    assert "not confirmed" in delegated["scheduling"]["message"]
    monkeypatch.setenv("OCTRYX_DISABLE_BACKGROUND_WORKERS", "0")
    assert (await cron_schedule.preview_schedule("0 9 * * *"))["scheduling"]["owner"] == "this_process"


async def test_never_firing_proof_runs_off_the_event_loop(monkeypatch):
    threads: list[int] = []
    real = cron_schedule._schedulable_problem

    def _spy(*args):
        threads.append(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(cron_schedule, "_schedulable_problem", _spy)
    with pytest.raises(Exception) as refused:
        await cron_schedule.require_schedulable_cron("0 0 31 4,6,9,11 *")
    assert refused.value.detail["code"] == "cron_never_fires"
    assert threads and threads[0] != threading.get_ident()


async def test_create_refuses_unschedulable_expressions_before_writing(admin_client, db):
    task = await _task(db)
    before = await _schedulers(db)
    for expr, code in (
        ("0 9 * * 7", "cron_field_invalid"),
        ("0 9 30 2 *", "cron_never_fires"),
        ("x" * 101, "cron_too_long"),
    ):
        refused = await admin_client.post(PANEL, json={"name": "s", "cron_expression": expr, "task_id": task.id})
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code, refused.text
    unknown = await admin_client.post(PANEL, json={"name": "s", "cron_expression": "0 9 * * *", "task_id": "no-such-task"})
    assert unknown.status_code == 404
    assert await _schedulers(db) == before, "no scheduler row written"
    created = await admin_client.post(PANEL, json={"name": "s", "cron_expression": "0 9 * * mon-fri", "task_id": task.id})
    assert created.status_code == 200 and created.json()["is_active"] is True


async def test_update_keeps_legacy_expression_and_paused_state_unless_explicitly_changed(admin_client, db):
    task = await _task(db)
    row = Scheduler(
        name="paused-invalid", cron_expression="0 9 30 2 *", task_id=task.id, is_active=False, owner_id=task.owner_id
    )
    db.add(row)
    await db.commit()

    metadata_only = await admin_client.put(f"{PANEL}/{row.id}", json={"name": "renamed", "description": "kept"})
    assert metadata_only.status_code == 200, metadata_only.text
    assert (metadata_only.json()["cron_expression"], metadata_only.json()["is_active"]) == ("0 9 30 2 *", False)

    for change, status in (({"cron_expression": "0 9 * * 7"}, 422), ({"task_id": "no-such-task"}, 404)):
        refused = await admin_client.put(f"{PANEL}/{row.id}", json={"description": "changed", **change})
        assert refused.status_code == status, refused.text
    await db.rollback()
    stored = await db.get(Scheduler, row.id)
    await db.refresh(stored)
    assert (stored.name, stored.description, stored.cron_expression, stored.task_id, stored.is_active) == (
        "renamed",
        "kept",
        "0 9 30 2 *",
        task.id,
        False,
    ), "a refused update changes nothing"

    fixed = await admin_client.put(f"{PANEL}/{row.id}", json={"cron_expression": "0 9 * * sun"})
    assert fixed.status_code == 200 and fixed.json()["cron_expression"] == "0 9 * * sun"
    assert fixed.json()["is_active"] is False, "editing never reactivates"


@pytest.mark.parametrize("expression", ["0 9 * * 0-4", "0 9 * * 0", "0 9 * * 6", "0 9 * * sun", "0 9 13 * fri"])
async def test_preview_matches_the_registered_trigger_run_for_run(monkeypatch, zurich, expression):
    calls: list[str] = []
    monkeypatch.setattr(
        registration_module, "build_cron_trigger", lambda e: calls.append(e) or cron_schedule.build_cron_trigger(e)
    )
    registration = SchedulerRegistrationMixin()
    registration.scheduler, registration.run_task_now, registration._loaded_task_ids = Mock(), Mock(), set()
    registration._register_job(ScheduleRecord(SCHEDULER_KIND, "s", expression, "t", "", "fingerprint"))
    assert calls == [expression], "registration builds its trigger through the shared builder"
    trigger = registration.scheduler.add_job.call_args.kwargs["trigger"]

    now = datetime(2026, 10, 4, 8, tzinfo=UTC)
    registered, previous = [], None
    for _ in range(5):
        previous = trigger.get_next_fire_time(previous, previous or now)
        registered.append(previous.astimezone(UTC).isoformat().replace("+00:00", "Z"))
    preview = await cron_schedule.preview_schedule(expression, 5, now=now)
    assert _at_utc(preview) == registered


async def test_dst_gap_and_repeat_are_reported_from_the_engine(zurich):
    spring = await cron_schedule.preview_schedule("30 2 * * *", 3, now=datetime(2026, 3, 28, 12, tzinfo=UTC))
    assert _at_utc(spring) == ["2026-03-29T01:30:00Z", "2026-03-30T00:30:00Z", "2026-03-31T00:30:00Z"]
    gap = spring["next_runs"][0]
    assert gap["local"] == "2026-03-29T03:30:00+02:00" and gap["dst_gap"] is True, "rendered from the instant"

    fall = await cron_schedule.preview_schedule("30 2 * * *", 3, now=datetime(2026, 10, 24, 12, tzinfo=UTC))
    assert _at_utc(fall) == ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z", "2026-10-26T01:30:00Z"]
    assert [run["dst_repeat"] for run in fall["next_runs"]] == [False, True, False]
    assert fall["truncated"] is False and fall["warning"] is None


async def test_a_sequence_that_stops_increasing_is_cut_off_not_invented(monkeypatch):
    fires = [datetime(2026, 10, 25, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 0, 0, tzinfo=UTC)]
    calls: list[int] = []

    class _Engine:
        timezone = UTC

        def get_next_fire_time(self, previous, now):
            calls.append(1)
            return fires[0] if previous is None else fires[1]

    monkeypatch.setattr(cron_schedule, "build_cron_trigger", lambda _e: _Engine())
    result = await cron_schedule.preview_schedule("*/30 2 * * *", 10, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert _at_utc(result) == ["2026-10-25T00:30:00Z"]
    assert result["truncated"] is True and result["warning"]["code"] == "engine_sequence_not_increasing"
    assert result["valid"] is True and len(calls) == 2, "stops at the first non-increasing time"
