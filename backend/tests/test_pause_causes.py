"""Controls audit: every pause names who caused it (platform, agent, environment, person),
as data, in the paused event, the run view and the metric octryx_run_pauses_total{cause, reason}."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.pause_causes import _data, cause_of, causes, metric_reason
from app.services.workflow_runs.states import PAUSE_REASONS


def test_every_pause_reason_has_a_cause_and_every_cause_is_known():
    data = _data()
    assert set(PAUSE_REASONS) - {"runtime_failed", "action_failed"} <= set(data["reasons"])
    used = {*data["reasons"].values(), *data["runtime_failed_codes"].values(), *data["runtime_failed_prefixes"].values(),
            *data["action_failed_classes"].values(), data["action_failed_default"], data["unmapped"]}
    assert used <= set(causes()) == {"platform", "agent", "environment", "person"}


@pytest.mark.parametrize(("reason", "detail", "cause"), [
    ("evidence_unresolved", {}, "platform"),
    ("loop_limit", {"edge_id": "e"}, "agent"),
    ("environment_not_ready", {}, "environment"),
    ("approval_timeout", {}, "person"),
    ("runtime_failed", {"code": "phase_not_finished"}, "agent"),
    ("runtime_failed", {"code": "device_turn_service_restarted"}, "platform"),
    ("runtime_failed", {"code": "device_turn_codex_exit_-15"}, "environment"),
    ("runtime_failed", {"code": "server_turn_refused_principal"}, "platform"),
    ("action_failed", {"failure_class": "permission"}, "person"),
    ("action_failed", {"failure_class": "transient"}, "environment"),
])
def test_the_cause_comes_from_the_data(reason, detail, cause):
    assert cause_of(reason, detail)[0] == cause


def test_an_unmapped_pause_counts_as_platform_and_says_so():
    assert cause_of("something_new", {}) == ("platform", "unmapped")
    assert cause_of("runtime_failed", {"code": "brand_new"}) == ("platform", "unmapped")
    assert metric_reason("runtime_failed", {"code": "phase_stalled"}) == "runtime_failed:phase_stalled"
    assert metric_reason("loop_limit", {"code": "x"}) == "loop_limit"


@pytest.mark.asyncio
async def test_a_pause_records_its_cause_in_the_event_the_view_and_the_metric(db):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from app.services.observability import workflow_metrics
    from app.services.workflow_runs.limits import pause_run
    from app.services.workflow_runs.records import new_chat_session, start_run
    from app.services.workflow_runs.views import _pause
    from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
    from tests.workflow_run_pipeline_support import _definition

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition()),
                          project_id=workspace_id, session=session)
    await pause_run(db, run, reason="runtime_failed", actor_id=None, detail={"code": "device_turn_error"})
    await db.flush()
    [event] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "paused"))).scalars().all()
    assert (event.detail["cause"], event.detail["cause_rule"]) == ("platform",
                                                                   "runtime_failed_codes.device_turn_error")
    assert (_pause(run)["cause"], _pause(run)["cause_rule"]) == ("platform", "runtime_failed_codes.device_turn_error")
    workflow_metrics.run_event(None, event)()
    rendered = "\n".join(workflow_metrics.PAUSES_BY_CAUSE.render())
    # #runtime_failed split: the pause is its class, turn_failed; the code still decides the cause.
    assert 'cause="platform",reason="turn_failed"' in rendered
    assert (run.pause_reason, event.detail["code"]) == ("turn_failed", "device_turn_error")
    assert "alias" not in event.detail


@pytest.mark.parametrize(("code", "reason"), [
    ("phase_not_finished", "phase_not_finished"), ("phase_stalled", "phase_stalled"), ("agent_loop", "agent_loop"),
    ("device_turn_service_restarted", "service_restarted"), ("interrupted_by_restart", "service_restarted"),
    ("device_turn_codex_exit_-15", "turn_failed"), ("server_turn_refused_principal", "turn_failed"),
    ("seat_limited_no_same_class_fallback", "seat_limit"), ("hands_on_scenarios_failed", "scenarios_failed"),
    ("something_new", "runtime_failed"), ("", "runtime_failed"),
])
def test_runtime_failed_splits_into_its_class_by_the_code(code, reason):
    """runtime_failed must not carry ten meanings told apart only by detail.code."""
    from app.services.workflow_runs.pause_causes import split_reason

    assert split_reason("runtime_failed", {"code": code}) == reason
    assert split_reason("loop_limit", {"code": code}) == "loop_limit"


def test_a_phase_not_finished_after_an_unsure_stop_check_is_the_platforms_pause():
    """With the fix in and `node --test test/` green, a check_uncertain on stop:declared_tests is the platform's
    doubt, not the agent's work, and must not make the Stop say not done."""
    base = {"code": "phase_not_finished"}
    assert cause_of("phase_not_finished", {**base, "uncertain_checks": ["stop:declared_tests"]}) == (
        "platform", "uncertain_check.stop:declared_tests")
    assert cause_of("phase_not_finished", {**base, "uncertain_checks": ["gate:green:tests_green"]})[0] == "agent"
    assert cause_of("phase_not_finished", base) == ("agent", "runtime_failed_codes.phase_not_finished")


def test_the_unsure_controls_are_those_of_the_current_pass():
    from types import SimpleNamespace

    from app.services.workflow_runs import uncertain

    events = []
    run = SimpleNamespace(context={}, current_node_id="fix", node_state={"entry": 2}, id="r")
    import app.services.workflow_runs.records as records

    original, records.record_event = records.record_event, lambda *args, **kwargs: events.append(kwargs)
    try:
        uncertain.note(None, run, control="stop:declared_tests", reason="summary cut")
        assert uncertain.controls_in_pass(run) == ["stop:declared_tests"] and len(events) == 1
        run.node_state = {"entry": 3}  # the next pass
        assert uncertain.controls_in_pass(run) == []
    finally:
        records.record_event = original
