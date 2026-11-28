"""What runs now as in-memory gauges on /metrics (services/observability/live_state.py); rendering them reads
nothing from the database."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.models import (
    DeviceJob,
    Project,
    UsageEvent,
    UserDevice,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
    WorkItem,
)
from app.services.observability import agent_metrics, live_state
from app.services.observability.metrics_render import render_worker_metrics
from app.time_utils import utc_now
from tests.observability_support import admin_user, call_as, session_for, workspace


@pytest.fixture(autouse=True)
def _empty():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _value(text: str, line_start: str) -> float:
    found = [line for line in text.splitlines() if line.startswith(line_start + " ")]
    assert len(found) == 1, (line_start, [line for line in text.splitlines() if line.startswith(line_start[:40])])
    return float(found[0].rsplit(" ", 1)[1])


async def _scene(db):
    admin = await admin_user(db)
    project = await workspace(db, "Coffee Bench")
    item = WorkItem(project_id=project.id, source_key="CAF-30", title="Story", epic_key="CAF-24")
    db.add(item)
    await db.flush()
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="epic-delivery", title="t",
                      requested_by=admin.id, status="running", ticket_key="CAF-30", current_node_id="implement",
                      work_item_id=item.id)
    session = await session_for(db, admin, project=project)
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uuid.uuid4().hex[:6]}", os="macos",
                        public_key="k")
    db.add_all([run, device])
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main"))
    await db.flush()
    db.add_all([
        WorkflowRunEvent(run_id=run.id, kind="review_verdict", node_id="independent_review",
                         detail={"verdict": "changes", "findings": 3, "reviewer_engine": "codex",
                                 "reviewer_model": "gpt-6-luna"}),
        WorkflowRunEvent(run_id=run.id, kind="pipeline_reported", node_id="pipeline",
                         detail={"state": "red", "unproven": ["e2e"]}),
        WorkflowRunEvent(run_id=run.id, kind="phase_turn", node_id="implement", detail={"state": "passed"}),
        UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider="openai_codex_seat",
                   model="gpt-6.1-sol", tokens_in=100, tokens_out=40, cache_read_tokens=1000, cost=Decimal("0")),
        DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=session.id, folder="/w", profile="seat",
                  engine="codex", status="running", turn_state="accepted", turn_count=4, model="gpt-6.1-sol",
                  usage={"input_tokens": 183883, "output_tokens": 44505}),
    ])
    await db.commit()
    return run.id, project.id, item.id


@pytest.mark.asyncio
async def test_written_work_becomes_live_series_by_id_without_reading_the_database(client, db):
    run_id, project_id, _item_id = await _scene(db)
    run = f'run="{run_id[:12]}",ticket="CAF-30"'

    text = (await call_as(client, "GET", "/metrics", await admin_user(db))).text

    state = [line for line in text.splitlines() if line.startswith(f"octryx_workflow_run_state{{{run},")]
    assert state == [line for line in state if 'workflow="epic-delivery",workspace="Coffee Bench",epic="CAF-24",'
                     'phase="implement",status="running",waiting_kind="none",pause_reason="none"}' in line]
    assert len(state) == 1 and abs(float(state[0].rsplit(" ", 1)[1]) - time.time()) < 60
    assert project_id not in text  # the Workspace by its name
    assert _value(text, f'octryx_workflow_run_last_event_timestamp_seconds{{{run},event="phase_turn"}}') > 0
    assert _value(text, f'octryx_workflow_run_tokens{{{run},workflow="epic-delivery",type="cache_read"}}') == 1000
    assert _value(text, f'octryx_review_last_findings{{{run}}}') == 3
    assert f'octryx_review_last_verdict{{{run},phase="independent_review",verdict="changes",engine="codex",' \
           'model="gpt-6-luna"}' in text
    assert f'octryx_pipeline_last_state{{{run},state="red"}}' in text
    assert _value(text, f'octryx_pipeline_unproven{{{run}}}') == 1
    job = next(line for line in text.splitlines() if line.startswith("octryx_device_job_state{"))
    assert 'ticket="CAF-30",engine="codex",workflow="epic-delivery",phase="implement",profile="seat",' \
           'model="gpt-6.1-sol",status="running",turn_state="accepted"}' in job
    assert any(line.startswith("octryx_device_job_tokens{") and 'type="output"} 44505' in line
               for line in text.splitlines())

    # The run finishes: its newest series says so, with when.
    finished = await db.get(WorkflowRun, run_id)
    finished.status, finished.completed_at = "completed", utc_now()
    await db.commit()
    text = "\n".join(agent_metrics.render())
    assert 'status="completed"' in next(line for line in text.splitlines()
                                         if line.startswith(f"octryx_workflow_run_state{{{run},"))
    assert _value(text, f'octryx_workflow_run_finished_timestamp_seconds{{{run},workflow="epic-delivery"}}') > 0


@pytest.mark.asyncio
async def test_names_and_epics_come_from_rows_requests_load_anyway(client, db):
    run_id, project_id, item_id = await _scene(db)
    live_state.WORKSPACE_NAMES.clear()
    live_state.EPIC_OF_ITEM.clear()
    run = f'run="{run_id[:12]}",ticket="CAF-30"'
    assert f'workspace="{project_id}",epic="none"' in next(
        line for line in agent_metrics.render() if line.startswith(f"octryx_workflow_run_state{{{run},"))

    db.expunge_all()
    await db.execute(select(Project).where(Project.id == project_id))
    await db.execute(select(WorkItem).where(WorkItem.id == item_id))
    assert 'workspace="Coffee Bench",epic="CAF-24"' in next(
        line for line in agent_metrics.render() if line.startswith(f"octryx_workflow_run_state{{{run},"))


@pytest.mark.asyncio
async def test_rendering_the_agent_metrics_runs_no_statement(db):
    await _scene(db)
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    class _NoDatabase:
        def __call__(self, *args, **kwargs):
            raise AssertionError("the agent metrics must not open a database session")

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        body = await render_worker_metrics(_NoDatabase())
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert statements == []
    assert 'ticket="CAF-30"' in body


def test_objects_leave_after_24_hours_and_stay_bounded():
    now = time.time()
    live_state.RUNS.update("old", now - live_state.KEEP_SECONDS - 1, status="paused")
    live_state.RUNS.update("new", now, status="running")
    assert [object_id for object_id, _entry in live_state.RUNS.current(now)] == ["new"]
    for index in range(live_state.MAX_OBJECTS + 5):
        live_state.JOBS.update(f"job-{index}", now, status="running")
    assert len(live_state.JOBS.current(now)) == live_state.MAX_OBJECTS


def test_the_table_totals_are_gone_and_the_operation_counters_are_declared():
    text = "\n".join(agent_metrics.render())
    for name in ("octryx_task_runs_enqueued_total", "octryx_task_runs_started_total", "octryx_task_runs_finished_total",
                 "octryx_code_graph_index_runs_total", "octryx_sla_breaches_recorded_total",
                 "octryx_outbound_webhook_delivery_status_total", "octryx_secret_rotation_logged_total"):
        assert f"# TYPE {name} counter" in text


@pytest.mark.asyncio
async def test_task_runs_count_when_queued_started_and_finished(db):
    from app.models import Task, TaskRun

    admin = await admin_user(db)
    task = Task(dispatch_binding="task_definition", name="nightly", owner_id=admin.id)
    db.add(task)
    await db.flush()
    run = TaskRun(task_id=task.id, trigger_type="cron", status="queued", started_by=admin.id)
    db.add(run)
    await db.commit()
    run.status = "running"
    await db.commit()
    run.status = "completed"
    await db.commit()

    text = "\n".join(agent_metrics.render())
    assert 'octryx_task_runs_enqueued_total{kind="cron"} 1' in text
    assert 'octryx_task_runs_started_total{kind="cron"} 1' in text
    assert 'octryx_task_runs_finished_total{kind="cron",status="completed"} 1' in text
