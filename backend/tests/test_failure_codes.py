"""Structured failure codes: a deterministic configuration failure pauses once
with what to fix and uses no loop round; a loop_limit pause takes its cause from the last failure's code."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.failure_codes import cause_of_failure, deterministic
from app.services.workflow_runs.hands_on import step
from app.services.workflow_runs.pause_causes import cause_of
from tests.hands_on_support import _answer, _at_hands_on, _Model


@pytest.mark.parametrize(("failure", "cause"), [
    ({"code": "serve_missing"}, "environment"), ({"code": "app_killed"}, "environment"),
    ({"code": "app_exited"}, "environment"), ({"code": "scenario_file_invalid"}, "agent"),
    ({"code": "unknown_code", "reason": "the app exited on http://127.0.0.1:1/"}, "agent"),
])
def test_the_cause_of_a_failure_comes_from_its_code_never_its_reason_text(failure, cause):
    assert cause_of_failure(failure)[0] == cause
    assert cause_of("loop_limit", {"edge_id": "e", "last_failure": failure})[0] == cause


def test_which_failures_are_deterministic_is_data_and_a_node_may_add():
    assert deterministic("serve_missing") and deterministic("env_file_invalid")
    assert not deterministic("app_exited") and not deterministic("")
    assert deterministic("app_exited", {"deterministic_failures": ["app_exited"]})


@pytest.mark.asyncio
async def test_a_missing_serve_pauses_once_and_uses_no_loop_round(db, monkeypatch):
    """Nightly dc263943: the environment file declared a UI but no serve; the hands-on loop used 3 rounds in 1 s."""
    run, session, offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "unavailable", "code": "serve_missing",
              "problem": 'The environment file declares a UI (system_test or browser) but no "serve".'}
    assert await step.record_report(db, run, report, session_id=session.id) == "red"
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "needs_configuration", "hands_on")
    pause = run.node_state["pause"]
    assert (pause["code"], pause["cause"]) == ("serve_missing", "environment") and "Next:" in pause["message"]
    await db.flush()
    loops = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "loop_iteration"))).scalars().all()
    assert loops == [] and offered.count("work") <= 1  # no round back to the building phase


@pytest.mark.asyncio
async def test_a_red_pass_records_its_code_for_the_loop_limits_cause(db, monkeypatch):
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "unavailable", "code": "app_killed",
              "problem": "the app (x) was killed on http://127.0.0.1:1/"}
    assert await step.record_report(db, run, report, session_id=session.id) == "red"
    assert run.context["last_failure"]["hands_on"]["code"] == "app_killed"
