"""What makes phases end unfinished and loops run on."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.hands_on import step
from app.services.workflow_runs.octryx.system_tests import phase_system_tests
from app.services.workflow_runs.phase_contract import WARNINGS_RULE
from app.services.workflow_runs.pipeline import CONTEXT_KEY as PIPELINE_KEY
from tests.hands_on_support import _answer, _at_hands_on, _Model
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

SYSTEM = "npx playwright test"
ENVIRONMENT = {"test": "flutter test", "system_test": SYSTEM}


@pytest.mark.parametrize("plain", [False, True])
def test_left_to_the_pipeline_the_rule_never_asks_the_agent_to_run_the_system_test(plain):
    asked = phase_system_tests("change", ENVIRONMENT, plain=plain)
    left = phase_system_tests("change", ENVIRONMENT, plain=plain, by_pipeline=True)
    assert left["by_pipeline"] is True and left["command"] == SYSTEM
    assert "do not run" in left["rule"].lower() and "pipeline" in left["rule"]
    assert "by_pipeline" not in asked and asked["rule"] != left["rule"]


def test_the_style_warnings_say_they_are_not_the_phase_s_task():
    assert "never block" in WARNINGS_RULE and "not this phase's task" in WARNINGS_RULE


def _red(view):
    return {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": False, "failed_step": 2, "error": "'Created: Bohne 1' is not shown"},
        {"id": "S2", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}


@pytest.mark.asyncio
async def test_an_unchanged_tree_after_a_red_hands_on_pauses_instead_of_running_again(db, monkeypatch):
    from app.services.workflow_runs.graph import graph_for_run

    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    run.context = {**dict(run.context or {}), PIPELINE_KEY: {"tree": "a" * 40}}
    assert await step.record_report(db, run, _red(step.contract_view(run)), session_id=session.id) == "red"
    node = (await graph_for_run(db, run)).nodes["hands_on"]

    await step.start(db, run, node)  # the agent's pass changed nothing: same tree
    assert run.status == "paused" and run.pause_reason == "agent_loop"
    assert step.state(run)["state"] == "red"

    await step.start(db, run, node)  # a person retries after the pause: it runs
    assert step.state(run)["state"] == "pending"


@pytest.mark.asyncio
async def test_a_changed_tree_runs_the_scenarios_again(db, monkeypatch):
    from app.services.workflow_runs.graph import graph_for_run

    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    run.context = {**dict(run.context or {}), PIPELINE_KEY: {"tree": "a" * 40}}
    await step.record_report(db, run, _red(step.contract_view(run)), session_id=session.id)
    run.context = {**dict(run.context or {}), PIPELINE_KEY: {"tree": "b" * 40}}
    await step.start(db, run, (await graph_for_run(db, run)).nodes["hands_on"])
    assert run.status != "paused" and step.state(run)["state"] == "pending"
