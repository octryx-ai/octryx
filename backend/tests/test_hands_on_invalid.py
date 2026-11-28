"""A platform-written feature scenario that tests nothing never sends the fix back."""

from __future__ import annotations

import pytest

from app.services.observability import hands_on_metrics
from app.services.workflow_runs.hands_on import step
from app.services.workflow_runs.hands_on.scenarios import COVERS, ScenarioError, validate
from tests.hands_on_support import _answer, _at_hands_on, _Model
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def list_events(db, run_id: str) -> list:
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    return list((await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run_id)
                                  .order_by(WorkflowRunEvent.created_at))).scalars())


@pytest.mark.asyncio
async def test_an_invalid_feature_scenario_is_reported_counted_and_remembered_never_red(db, monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs.hands_on.invalid import keeps_data
    from app.services.workflow_runs.run_memory import store as memory_store

    hands_on_metrics.reset()
    record = SimpleNamespace(config_json={})

    async def record_of(_db, _run):
        return record

    monkeypatch.setattr(memory_store, "record_of", record_of)
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    run.repository = "github:octryx-ai/bench"  # the run memory lives on the repository's record
    view = step.contract_view(run)
    assert await keeps_data(db, run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": False, "failed_step": 2, "error": "nothing visible shows 'M1'",
         "invalid": {"reason": "data_lost_after_restart", "base": "b" * 40, "error": "nothing visible shows 'M1'"}},
        {"id": "S2", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "green"
    (kept,) = [item for item in step.run_view(run)["results"] if item.get("invalid")]
    assert kept["id"] == "S1" and kept["invalid"] == "data_lost_after_restart"
    events = [event for event in await list_events(db, run.id) if event.kind == "hands_on_scenario_invalid"]
    assert events and events[0].detail["reason"] == "data_lost_after_restart"
    reported = [event for event in await list_events(db, run.id) if event.kind == "hands_on_reported"][-1]
    assert reported.detail["scenarios"][0]["error"] == "nothing visible shows 'M1'"
    assert hands_on_metrics.INVALID.series
    assert not await keeps_data(db, run)  # the run memory learned it: the next scenarios seed in-session


@pytest.mark.asyncio
async def test_a_red_feature_scenario_without_the_base_mark_stays_red_with_its_message(db, monkeypatch):
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": False, "failed_step": 2, "error": "'15' is not shown"},
        {"id": "S2", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "red"
    failed = [event for event in await list_events(db, run.id) if event.kind == "platform_action"][-1]
    assert "'15' is not shown" in str(failed.detail.get("reason"))


def test_an_app_without_persistence_gets_scenarios_that_seed_in_their_own_steps():
    answer = _answer()
    validate(answer, required=COVERS)
    with pytest.raises(ScenarioError, match="keeps no data across a restart"):
        validate(required=COVERS, answer={"scenarios": [{**item, "seed": [{"do": "goto", "path": "/"}], "fresh_profile": False}
                                if item.get("part") == "feature" else item for item in answer["scenarios"]]},
                 keeps_data=False)
    no_reload = {"scenarios": [{**item, "covers": [c for c in item.get("covers", []) if c != "persistence_reload"],
                                "fresh_profile": True, "seed": []} for item in answer["scenarios"]]}
    with pytest.raises(ScenarioError):
        validate(no_reload, required=COVERS)
    validate(no_reload, required=COVERS, keeps_data=False)  # no persistence_reload cover needed then


@pytest.mark.asyncio
async def test_an_app_without_a_ui_skips_before_any_scenario_is_written(db, monkeypatch):
    model = _Model(_answer())
    run, _session, _offered, _factory = await _at_hands_on(db, monkeypatch, model=model)
    run.context = {**dict(run.context or {}), "contract_pin": {
        "file": "e2e/python/.octryx/environment.json", "sha256": "a" * 64,
        "environment": {"test": "python3 -m pytest -q", "setup": [], "check": []}}}
    from app.services.workflow_runs.graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes[run.current_node_id]
    outcome, route = await step.start(db, run, node)
    assert outcome.result == {"skipped": "the environment file declares no UI (no serve, system_test or browser)"}
    assert route == "succeeded" and not model.asked


def test_an_unknown_key_of_the_environment_file_is_a_warning_and_the_file_stays_valid():
    from app.services.workflow_runs.workspace.spec import validate_environment

    raw = {"test": "python3 -m pytest -q", "colour": "blue",
           "serve": {"command": "npm start", "url": "http://127.0.0.1:3000/", "future_flag": True}}
    environment, errors = validate_environment(raw)
    assert errors == [] and environment["serve"]["url"] == "http://127.0.0.1:3000/"
    assert any("colour" in item for item in environment["warnings"])
    assert any("future_flag" in item and "newer platform" in item for item in environment["warnings"])
    _environment, errors = validate_environment({**raw, "serve": {**raw["serve"], "persistent": "no"}})
    assert errors and "persistent" in errors[0]


@pytest.mark.asyncio
async def test_a_failed_setup_step_is_remembered_and_the_next_writer_is_told(db, monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs.hands_on.generate import write_scenarios
    from app.services.workflow_runs.run_memory import store as memory_store

    record = SimpleNamespace(config_json={})

    async def record_of(_db, _run):
        return record

    monkeypatch.setattr(memory_store, "record_of", record_of)
    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    run.repository = "github:octryx-ai/bench"
    view = step.contract_view(run)
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": False, "failed_step": 2, "error": "nothing visible shows 'Brew'",
         "invalid": {"reason": "setup_fails_on_base", "base": "b" * 40, "error": "nothing visible shows 'Brew'"}},
        {"id": "S2", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "green"
    writer = _Model(_answer())
    await write_scenarios(db, run, writer, "Write the scenarios.", required=COVERS)
    told = writer.asked[0]
    assert "Save (or submit) button" in told  # the platform's hint (stacks.json general.scenario_hints)
    assert "setup step failed on this app's base" in told and "nothing visible shows 'Brew'" in told
