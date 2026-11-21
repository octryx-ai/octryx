"""The hands-on test: scenarios the platform writes, run on the device, red back to the building agent (pipelines
and reviews alone can pass an app that loses its data on reload)."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.hands_on import step
from app.services.workflow_runs.hands_on.scenarios import ScenarioError, validate
from tests.hands_on_support import _answer, _at_hands_on, _Model, _reproduce_definition, _scenario


def test_the_scenarios_cover_the_feature_and_the_whole_regression_set():
    scenarios = validate(_answer())
    assert [item["id"] for item in scenarios] == ["S1", "S2", "S3", "S4"]
    assert scenarios[3]["fresh_profile"] is False and scenarios[3]["seed"] == [{"do": "click", "text": "Skip"}]
    for broken, why in [
        ({"scenarios": _answer()["scenarios"][1:]}, "at least one feature scenario"),
        ({"scenarios": _answer()["scenarios"][:2]}, "do not cover: mobile_390, desktop_1280"),
        ({"scenarios": [*_answer()["scenarios"][:2], _scenario(covers=("mobile_390",), width=400)]},
         "mobile_390 needs the viewport width 390"),
        ({"scenarios": [_answer()["scenarios"][0], {**_scenario(covers=("persistence_reload",)), "steps": [
            {"do": "goto", "path": "/"}]}]}, "persistence_reload needs a reload or restart"),
        ({"scenarios": [{**_scenario("feature"), "fresh_profile": False}]}, "seed: 1 to 40 steps"),
        ({"scenarios": [{**_scenario("feature"), "steps": [{"do": "eval", "text": "x"}]}]}, 'a step needs "do"'),
        ({"scenarios": [{**_scenario("feature"), "steps": [{"do": "goto", "path": "http://evil"}]}]}, "path"),
    ]:
        with pytest.raises(ScenarioError, match=why):
            validate(broken)


@pytest.mark.asyncio
async def test_the_platform_writes_the_scenarios_offers_the_device_and_a_green_report_goes_on(db, monkeypatch):
    model = _Model({"scenarios": "nope"}, _answer())
    run, session, offered, factory = await _at_hands_on(db, monkeypatch, model=model)
    assert run.current_node_id == "hands_on" and step.state(run)["state"] == "generating"
    assert step.contract_view(run) is None  # nothing for the device before the scenarios exist
    assert await step.generate_due(db, model_factory=factory) == 1
    run = await db.get(type(run), run.id)
    assert "Your earlier answers were refused" in model.asked[1] and offered == ["hands_on"]
    view = step.contract_view(run)
    assert [item["id"] for item in view["scenarios"]] == ["S1", "S2", "S3", "S4"]
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran",
              "scenarios": [{"id": f"S{n}", "passed": True, "screenshots": [f"hands-on-s{n}-end.png"]}
                            for n in range(1, 5)]}
    assert await step.record_report(db, run, report, session_id=session.id) == "green"
    assert run.status == "completed" and step.run_view(run)["state"] == "green"


@pytest.mark.asyncio
async def test_a_failed_scenario_goes_back_to_the_agent_with_its_step_and_the_same_scenarios_run_again(db,
                                                                                                    monkeypatch):
    run, session, offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": True}, {"id": "S2", "passed": False, "failed_step": 2,
                                       "error": "'Bohne 1' is not shown", "screenshots": ["hands-on-s2-failed.png"]},
        {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "red"
    assert run.current_node_id == "work"
    red = step.failure_for_agent(run)
    (failed,) = red["failed"]
    assert failed["failed_step"] == "3: expect_text text='Bohne 1'" and failed["screenshots"] == [
        "hands-on-s2-failed.png"]
    assert "Bohne 1" not in str([item for item in red["failed"] if item["id"] != "S2"])  # passing steps stay hidden
    # The loop's next pass reuses the run's scenarios: offered at once, no new model call.
    from app.services.workflow_runs.graph import graph_for_run

    await step.start(db, run, (await graph_for_run(db, run)).nodes["hands_on"])
    assert step.state(run)["state"] == "pending" and offered[-1] == "hands_on"


@pytest.mark.asyncio
async def test_unavailable_is_red_with_the_reason_and_skipped_goes_on(db, monkeypatch):
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    problem = 'The environment file declares a UI (system_test or browser) but no "serve"'
    unavailable = {"node_id": view["node_id"], "entry": view["entry"], "state": "unavailable", "problem": problem}
    assert await step.record_report(db, run, unavailable, session_id=session.id) == "red"
    assert step.failure_for_agent(run)["reason"] == problem
    other, other_session, _o, other_factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=other_factory)
    other = await db.get(type(other), other.id)
    view = step.contract_view(other)
    skipped = {"node_id": view["node_id"], "entry": view["entry"], "state": "skipped", "reason": "no UI"}
    assert await step.record_report(db, other, skipped, session_id=other_session.id) == "skipped"
    assert other.status == "completed"


@pytest.mark.asyncio
async def test_a_server_run_no_environment_file_or_a_switched_off_workspace_skips(db, monkeypatch):
    run, _session, offered, _factory = await _at_hands_on(db, monkeypatch, runtime="server")
    assert run.status == "completed" and step.state(run)["reason"] == "no browser for a server run"
    run, _session, _offered, _factory = await _at_hands_on(db, monkeypatch, pointer=False)
    assert run.status == "completed" and "no environment file" in step.state(run)["reason"]
    assert offered == []


@pytest.mark.asyncio
async def test_no_valid_scenarios_is_red_with_why(db, monkeypatch):
    run, _session, offered, factory = await _at_hands_on(db, monkeypatch, model=_Model({}, {"scenarios": []}, {"scenarios": []}))
    assert await step.generate_due(db, model_factory=factory) == 1
    run = await db.get(type(run), run.id)
    # Controls audit: the platform's scenario writer failed, not the agent: the run pauses (cause
    # platform) at the step with why, instead of a red round back to the building phase.
    assert (run.status, run.current_node_id, offered) == ("paused", "hands_on", [])
    pause = run.node_state["pause"]
    assert (pause["code"], pause["cause"]) == ("hands_on_scenarios_failed", "platform")
    assert "the scenarios could not be written: attempt 1: scenarios: 1 to" in pause["message"]
    assert "attempt 2: scenarios: 1 to" in pause["message"] and "attempt 3: scenarios: 1 to" in pause["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("confirm", "scenario", "route", "state"), [
    (False, {"passed": False, "failed_op": "expect_text", "error": "'15' is not shown"}, "succeeded", "reproduced"),
    (True, {"passed": False, "failed_op": "expect_text", "error": "'15' is not shown"}, "skipped", "reproduced"),
    (False, {"passed": True}, "cannot_reproduce", "cannot_reproduce"),
    (False, {"passed": False, "failed_op": "click", "error": "nothing shows 'Add'"}, "failed", "repro_setup_failed"),
])
async def test_the_reproduce_check_routes_by_why_the_scenario_failed(db, monkeypatch, confirm, scenario, route, state):
    run, session, offered, _factory = await _at_hands_on(db, monkeypatch, definition=_reproduce_definition(confirm))
    view = step.contract_view(run)
    assert (view["mode"], offered) == ("reproduce", ["hands_on"])  # no scenario writing: the repository's own
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran",
              "scenarios": [{"id": "repo:tests/hands_on/bugs/OCX-1.json#1", **scenario}]}
    assert await step.record_report(db, run, report, session_id=session.id) == state
    assert run.context["hands_on_reproduce"]["state"] == state
    assert run.context["actions"]["hands_on"]["result"] == route
