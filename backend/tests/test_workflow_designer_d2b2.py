"""D2b2 (designer side panel, Decisions S3): the otherwise route, a phase's results, field conditions, four-eyes publish."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.phase_turns import complete_phase_turn
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_designer_d2b2_support import _codes, _edge, _outcome, result_definition

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _result_run(db, definition: dict):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=workspace_id)
    session = await new_bound_session(db, run, admin)
    return run, session


def test_every_value_needs_a_route_or_an_otherwise():
    assert validate_flow_definition(result_definition())["valid"] is True
    only_one = result_definition(options=["fix_needed"])
    only_one["edges"] = [edge for edge in only_one["edges"] if edge["id"] != "n"]
    assert "decision_unrouted" in _codes(only_one)
    with_otherwise = result_definition(options=["fix_needed"], otherwise=True)
    assert validate_flow_definition(with_otherwise)["valid"] is True


def test_otherwise_is_a_decision_route_at_most_once():
    twice = result_definition(options=["fix_needed"], otherwise=True)
    twice["edges"].append(_edge("n2", "pick", "fixed", "otherwise"))
    assert "duplicate_route" in _codes(twice)
    on_a_gate = phased_definition()
    on_a_gate["edges"][3]["when"] = "otherwise"
    assert "unknown_route" in _codes(on_a_gate)
    as_an_option = result_definition(options=["fix_needed", "otherwise"], otherwise=True)
    assert "decision_options" in _codes(as_an_option)


def test_a_decision_on_a_gate_must_route_both_of_its_values():
    definition = phased_definition(extra_nodes=[
        {"id": "pick", "type": "decision", "config": {"source": "verify", "options": ["passed"]}},
        _outcome("other", "blocked")])
    definition["edges"][2]["target_node_id"] = "pick"
    definition["edges"].append(_edge("p", "pick", "done", "passed"))
    assert "decision_unrouted" in _codes(definition)
    definition["edges"].append(_edge("o", "pick", "other", "otherwise"))
    assert validate_flow_definition(definition)["valid"] is True


@pytest.mark.parametrize("values", [["Fix needed"], ["fix", "fix"], ["otherwise"], "fix", [""]])
def test_result_values_are_distinct_snake_case_names(values):
    definition = result_definition()
    definition["nodes"][1]["config"]["result_values"] = values
    assert "phase_result_values" in _codes(definition)


def test_a_result_decision_names_only_the_phases_results():
    unknown = result_definition(options=["fix_needed", "maybe"])
    assert "decision_options" in _codes(unknown)
    undeclared = result_definition()
    undeclared["nodes"][1]["config"].pop("result_values")
    assert "decision_source" in _codes(undeclared)


@pytest.mark.asyncio
async def test_the_phase_records_its_result_and_the_decision_routes_on_it(db):
    run, session = await _result_run(db, result_definition())
    resolution = await run_turn_resolution(db, session, user_message="Assess it.")
    facts = resolution["workflow_contract"]["workflow_run_phase"]
    assert facts["result"] == {"tool": "submit_phase_result", "values": ["fix_needed", "no_fix"]}
    assert "submit_phase_result" in resolution["tool_policy"]["allowlist"]

    refused = await submit_output(db, run, "submit_phase_result", {"value": "maybe"})
    assert refused["state"] == "refused" and "fix_needed" in refused["message"]
    recorded = await submit_output(db, run, "submit_phase_result", {"value": "no_fix", "summary": "Works as is."})
    assert recorded["state"] == "recorded"

    await phase_turn(db, session.id, resolution, ["knowledge_search", "submit_phase_result"])
    assert (run.status, run.outcome, run.current_node_id) == ("completed", "blocked", "blocked")
    assert run.context["results"]["work"] == "no_fix"


@pytest.mark.asyncio
async def test_the_other_branch(db):
    run, session = await _result_run(db, result_definition())
    resolution = await run_turn_resolution(db, session, user_message="Assess it.")
    await submit_output(db, run, "submit_phase_result", {"value": "fix_needed"})
    await phase_turn(db, session.id, resolution, ["knowledge_search", "submit_phase_result"])
    assert (run.status, run.outcome) == ("completed", "done")


@pytest.mark.asyncio
async def test_an_unmatched_result_takes_the_otherwise_route(db):
    run, session = await _result_run(db, result_definition(options=["fix_needed"], otherwise=True))
    resolution = await run_turn_resolution(db, session, user_message="Assess it.")
    await submit_output(db, run, "submit_phase_result", {"value": "no_fix"})
    await phase_turn(db, session.id, resolution, ["knowledge_search", "submit_phase_result"])
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert run.context["results"]["pick"] == "otherwise"


@pytest.mark.asyncio
async def test_a_phase_without_a_recorded_result_is_not_done(db):
    run, session = await _result_run(db, result_definition())
    resolution = await run_turn_resolution(db, session, user_message="Assess it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    assert (run.status, run.current_node_id) == ("running", "work")
    await complete_phase_turn(db, run, node_id="work", state="passed", evidence=None)
    assert (run.status, run.current_node_id) == ("running", "work")
    events = (await db.execute(select(WorkflowRunEvent.kind).where(WorkflowRunEvent.run_id == run.id))).scalars()
    assert "phase_result_missing" in list(events)


@pytest.mark.asyncio
async def test_a_phase_without_result_values_does_not_take_a_result(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id)
    refused = await submit_output(db, run, "submit_phase_result", {"value": "done"})
    assert refused["state"] == "refused" and refused["reason"] == "outside_phase_output"
