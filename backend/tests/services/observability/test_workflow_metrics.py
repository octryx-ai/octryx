"""Workflow run, review, pipeline, device and seat-route counters on /metrics
(services/observability/workflow_metrics.py): what is committed counts, by workflow and phase, never by run id."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models import DeviceJob, UsageEvent, UserDevice, WorkflowRun, WorkflowRunEvent
from app.services.observability import agent_metrics, workflow_metrics
from app.time_utils import utc_now
from tests.observability_support import admin_user, call_as, session_for, workspace


@pytest.fixture(autouse=True)
def _empty_metrics():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _value(text: str, line_start: str) -> float:
    found = [line for line in text.splitlines() if line.startswith(line_start + " ")]
    assert len(found) == 1, (line_start, [line for line in text.splitlines() if line.startswith(line_start[:40])])
    return float(found[0].rsplit(" ", 1)[1])


def _event(run_id: str, event: str, node: str | None, **detail) -> WorkflowRunEvent:
    return WorkflowRunEvent(run_id=run_id, kind=event, node_id=node, detail=detail)


@pytest.mark.asyncio
async def test_run_events_count_by_workflow_phase_and_kind_with_their_details(client, db):
    admin = await admin_user(db)
    project = await workspace(db, "Coffee")
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="epic-delivery", title="t",
                      requested_by=admin.id, status="running")
    db.add(run)
    await db.commit()
    run_id, project_id = run.id, project.id
    db.add(_event(run_id, "node_entered", "implement", kind="phase"))
    await db.commit()

    db.add_all([
        _event(run_id, "phase_turn", "implement", state="failed"),
        _event(run_id, "phase_turn", "implement", state="passed"),
        _event(run_id, "run_turn_model_refused", "implement", model="claude-sonnet-5-5", profile="seat"),
        _event(run_id, "wip_pushed", "implement", state="pushed"),
        _event(run_id, "workspace_preparation_reported", "prepare", state="ready", runtime="device"),
        _event(run_id, "pipeline_reported", "pipeline", state="red", unproven=[]),
        _event(run_id, "review_verdict", "independent_review", verdict="changes", findings=3, reviewer_engine="codex",
               reviewer_model="gpt-6-luna", reviewer_route_used="seat",
               finding_list=[{"severity": "high"}, {"severity": "low"}, {"severity": "low"}]),
        _event(run_id, "paused", "independent_review", reason="review_no_decision", message="too large"),
    ])
    await db.commit()
    db.add(_event(run_id, "node_entered", "pipeline", kind="phase"))  # leaves "implement"
    await db.flush()
    await db.rollback()  # never happened: not counted
    db.add(_event(run_id, "node_entered", "pipeline", kind="phase"))
    await db.commit()
    run = await db.get(WorkflowRun, run_id)
    run.status, run.completed_at = "stopped", utc_now()
    db.add(_event(run_id, "stopped", "pipeline", reason="restarted"))
    await db.commit()

    text = (await call_as(client, "GET", "/metrics", await admin_user(db))).text
    wf = 'workflow="epic-delivery"'
    assert _value(text, f'octryx_workflow_run_events_total{{{wf},phase="implement",event="node_entered"}}') == 1
    assert _value(text, f'octryx_workflow_run_events_total{{{wf},phase="pipeline",event="node_entered"}}') == 1
    assert _value(text, f'octryx_workflow_phase_turns_total{{{wf},phase="implement",state="failed"}}') == 1
    assert _value(text, f'octryx_workflow_phase_turns_total{{{wf},phase="implement",state="passed"}}') == 1
    assert _value(text, 'octryx_run_turn_model_refused_total{model="claude-sonnet-5-5",profile="seat"}') == 1
    assert _value(text, 'octryx_wip_push_total{state="pushed"}') == 1
    assert _value(text, 'octryx_workspace_preparation_total{runtime="device",state="ready"}') == 1
    assert _value(text, f'octryx_pipeline_reports_total{{{wf},state="red"}}') == 1
    assert _value(text, f'octryx_pipeline_red_before_total{{{wf},result="proven"}}') == 1  # unproven=[]
    assert _value(text, f'octryx_review_verdicts_total{{{wf},phase="independent_review",engine="codex",'
                        'model="gpt-6-luna",route="seat",verdict="changes"}') == 1
    assert _value(text, f'octryx_review_findings_total{{{wf},severity="low"}}') == 2
    assert _value(text, f'octryx_review_findings_total{{{wf},severity="high"}}') == 1
    assert _value(text, f'octryx_workflow_run_pauses_total{{{wf},phase="independent_review",'
                        'reason="review_no_decision"}') == 1
    assert _value(text, f'octryx_workflow_run_stops_total{{{wf},phase="pipeline"}}') == 1
    # The phases it left: "implement" for the next one, "pipeline" when the run stopped.
    assert _value(text, f'octryx_workflow_phase_duration_seconds_count{{{wf},phase="implement",'
                        'outcome="next"}') == 1
    assert _value(text, f'octryx_workflow_phase_duration_seconds_count{{{wf},phase="pipeline",'
                        'outcome="stopped"}') == 1
    assert run_id not in text and project_id not in text


@pytest.mark.asyncio
async def test_device_turns_count_by_engine_model_and_outcome_with_their_duration(client, db):
    admin = await admin_user(db)
    session = await session_for(db, admin)
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uuid.uuid4().hex[:6]}", os="macos",
                        public_key="k")
    db.add(device)
    await db.flush()
    job = DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=session.id, folder="/w", profile="seat",
                    engine="codex", status="offered", turn_state="pending")
    db.add(job)
    await db.commit()
    job_id = job.id
    job = await db.get(DeviceJob, job_id)

    job.status, job.turn_state, job.model = "running", "accepted", "gpt-6.1-sol"
    await db.commit()
    job.status, job.turn_state = "idle", "done"
    await db.commit()
    job.status, job.turn_state = "running", "accepted"
    await db.commit()
    job.status, job.disconnected_at = "device_lost", utc_now()  # the device went away mid-turn
    await db.commit()

    text = (await call_as(client, "GET", "/metrics", await admin_user(db))).text
    codex = 'engine="codex",profile="seat",model="gpt-6.1-sol",effort="default"'
    assert _value(text, f'octryx_device_turns_total{{{codex},outcome="done"}}') == 1
    assert _value(text, f'octryx_device_turns_total{{{codex},outcome="device_lost"}}') == 1
    assert _value(text, 'octryx_device_turn_duration_seconds_count{engine="codex",profile="seat"}') == 2
    assert _value(text, 'octryx_device_job_disconnects_total{engine="codex"}') == 1
    # The wait for the device: from the job's creation to its first accepted turn, once (the second turn is no wait).
    assert _value(text, 'octryx_device_wait_seconds_count{engine="codex"}') == 1
    assert job_id not in text


@pytest.mark.asyncio
async def test_seat_usage_is_a_request_of_its_route_and_governed_usage_is_not_counted_twice(client, db):
    admin = await admin_user(db)
    session = await session_for(db, admin)

    def usage(provider: str, model: str, **fields) -> UsageEvent:
        return UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider=provider,
                          model=model, tokens_in=10, tokens_out=5, cost=Decimal("0"), **fields)

    with agent_metrics.seat_call(agent_metrics.ROUTE_GATEWAY, 2.0):
        db.add(usage("openai_codex_seat", "gpt-6.1-sol", cost_source="seat_subscription"))
        await db.commit()
    db.add_all([
        usage("anthropic_seat", "claude-sonnet-5-5", cost_source="seat_subscription"),
        usage("anthropic_seat", "claude-haiku-5-5", cost_source="seat_subscription",
              dispatch_owner="workflow_run_review"),
        usage("assistant", "assistant-large", dispatch_owner="engine_runtime_chain"),
        usage("bedrock", "claude-x"),  # governed: the provider wrapper counts its request
    ])
    await db.commit()

    text = (await call_as(client, "GET", "/metrics", await admin_user(db))).text
    codex = 'provider="openai_codex_seat",model="gpt-6.1-sol",route="gateway"'
    assert _value(text, f'octryx_llm_requests_total{{{codex},outcome="ok"}}') == 1
    assert _value(text, f'octryx_llm_request_duration_seconds_count{{{codex}}}') == 1
    assert _value(text, 'octryx_llm_requests_total{provider="anthropic_seat",model="claude-sonnet-5-5",'
                        'route="gateway",outcome="ok"}') == 1
    assert _value(text, 'octryx_llm_requests_total{provider="anthropic_seat",model="claude-haiku-5-5",'
                        'route="review",outcome="ok"}') == 1
    assert any(line.startswith('octryx_llm_tokens_total{provider="assistant",model="assistant-large",'
                               'route="engine_chain",type="input",engine="governed",role="engine_chain",')
               and line.endswith(" 10") for line in text.splitlines())
    assert any(line.startswith('octryx_llm_tokens_total{provider="bedrock",model="claude-x",route="governed",'
                               'type="output",engine="governed",') and line.endswith(" 5") for line in text.splitlines())
    assert 'octryx_llm_requests_total{provider="bedrock"' not in text
    assert 'octryx_llm_requests_total{provider="assistant"' not in text


def test_remembered_timings_stay_bounded():
    for index in range(workflow_metrics._REMEMBERED + 10):
        workflow_metrics._PHASE_ENTERED.put(f"run-{index}", ("implement", 0.0))
    assert len(workflow_metrics._PHASE_ENTERED) == workflow_metrics._REMEMBERED
    assert "run-0" not in workflow_metrics._PHASE_ENTERED
