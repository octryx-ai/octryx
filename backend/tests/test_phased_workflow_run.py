"""DevOps workflows S2: "Runs in phases" — the bounded state machine, its validation and its runtime gates."""

from __future__ import annotations

import copy

import pytest

from app.models import WorkflowRun
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.flow_definitions import validate_flow_definition
from app.services.flow_orchestration.dag.node_execution import _execute_node
from app.services.flow_version_state import FlowVersionStateError, ensure_runnable
from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_contracts.contract_message import build_workflow_contract_message
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.path_rules import blocked_paths, phase_path_outcomes
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_flow_definition(definition)["errors"]]


def test_a_phased_definition_is_validated_as_a_bounded_graph():
    assert validate_flow_definition(phased_definition())["valid"] is True
    unbounded = phased_definition()
    unbounded["edges"][-1].pop("max_iterations")
    assert "unbounded_loop" in _codes(unbounded)
    plain_cycle = phased_definition()
    plain_cycle["edges"][-1]["kind"] = "next"
    assert "cycle_without_loop_edge" in _codes(plain_cycle)
    forward_loop = phased_definition()
    forward_loop["edges"][-1]["target_node_id"] = "done"
    forward_loop["edges"][-1]["when"] = "failed"
    assert "loop_not_back_edge" in _codes(forward_loop)
    no_checks = phased_definition()
    no_checks["nodes"][1]["config"]["workflow_contract"].pop("checks")
    assert "phase_without_checks" in _codes(no_checks)
    unrouted = phased_definition()
    unrouted["edges"][2]["when"] = "maybe"
    assert "unknown_route" in _codes(unrouted)
    judged_answer = phased_definition()
    judged_answer["nodes"][2]["config"]["checks"][0]["type"] = "answer_contains_any"
    assert "gate_check_type" in _codes(judged_answer)


@pytest.mark.asyncio
async def test_the_dag_executor_refuses_a_phased_version_and_never_fabricates_a_stub_result(db):
    version = FlowDefinitionVersion(id="v", flow_id="f", version=1, status="published",
                                    definition_json=phased_definition())
    with pytest.raises(FlowVersionStateError) as refused:
        ensure_runnable(version)
    assert refused.value.reason == "flow_version_phased"
    for node_type in ("evaluation", "subflow"):
        with pytest.raises(Exception, match="workflow that runs in phases"):
            await _execute_node(db, orchestrator_run=None, node={"id": "n", "type": node_type, "config": {}},
                                input_snapshot={}, initial_input={}, project_id=None, project_config={},
                                user_id="u", agent_type="change", limits=None, usage=None)


@pytest.mark.asyncio
async def test_a_phased_run_loops_through_its_gate_and_pauses_at_the_loop_limit(db):
    admin = await admin_user(db)
    key = await publish_phased(db, phased_definition(max_iterations=1))
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    session = await new_bound_session(db, run, admin)
    assert (run.workflow_kind, run.status, run.current_node_id) == ("phased", "running", "work")

    resolution = await run_turn_resolution(db, session, user_message="Collect it.")
    assert resolution["workflow_run"]["node_id"] == "work"
    assert resolution["workflow_contract"]["capability_class"] == "read_only"
    assert resolution["tool_policy"]["allowlist"] == ["knowledge_search", "knowledge_read"]

    # Turn 1: the phase's own check passes, the gate does not: the bounded loop leads back to the phase.
    assert await phase_turn(db, session.id, resolution, ["knowledge_search"]) is None
    assert (run.status, run.current_node_id, run.node_state["iteration"]) == ("running", "work", 2)
    assert run.gate_results["verify"]["state"] == "failed"
    assert run.loop_counters["rework"]["used"] == 1
    second = await run_turn_resolution(db, session, user_message="Again.")
    assert second["workflow_contract"]["workflow_run_phase"] == {
        "title": "Collect evidence", "iteration": 2, "findings": ["A source was read"],
    }
    with prompt_set_scope(seed_prompt_set()):
        message = build_workflow_contract_message(
            {**second["workflow_contract"], "topic": "the item"}
        )
    assert "iteration 2" in message and "A source was read" in message

    # Turn 2: the gate fails again and the loop is at its limit of 1: the run pauses, it never stops silently.
    await phase_turn(db, session.id, second, ["knowledge_search"])
    assert (run.status, run.pause_reason) == ("paused", "loop_limit")
    held = await run_turn_resolution(db, session, user_message="Go on.")
    assert (held["status"], held["profile_status"]) == ("held", "needs_clarification")
    assert "paused" in held["unmatched_reason"]


@pytest.mark.asyncio
async def test_a_passing_gate_ends_the_run_with_its_outcome(db):
    admin = await admin_user(db)
    key = await publish_phased(db, phased_definition())
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    session = await new_bound_session(db, run, admin)
    resolution = await run_turn_resolution(db, session, user_message="Collect it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search", "knowledge_read"])
    assert (run.status, run.outcome, run.current_node_id) == ("completed", "done", "done")
    assert await run_turn_resolution(db, session, user_message="More?") is None


@pytest.mark.asyncio
async def test_a_phase_path_rule_blocks_writes_outside_its_patterns(db):
    assert blocked_paths(["tests/test_a.py", "src/a.py"], ["tests/**"]) == ["src/a.py"]
    admin = await admin_user(db)
    definition = phased_definition()
    contract = definition["nodes"][1]["config"]["workflow_contract"]
    contract["path_rules"] = {"write": ["tests/**"]}
    key = await publish_phased(db, definition)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    session = await new_bound_session(db, run, admin)
    outcomes = await phase_path_outcomes(db, session.id, ["tests/test_a.py", "src/a.py"])
    assert [(item["effect"], item["evidence"]["paths"]) for item in outcomes] == [("block", ["src/a.py"])]


@pytest.mark.asyncio
async def test_a_sub_workflow_runs_its_child_in_the_parents_session_and_routes_on_its_outcome(db):
    admin = await admin_user(db)
    child_key = await publish_phased(db, phased_definition())
    parent_definition = copy.deepcopy(phased_definition())
    parent_definition["nodes"] = [
        {"id": "start", "type": "start"},
        {"id": "child", "type": "sub_workflow", "label": "Evidence", "config": {"workflow_key": child_key}},
        {"id": "ok", "type": "outcome", "config": {"outcome": "delivered"}},
        {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}},
    ]
    parent_definition["edges"] = [
        {"id": "p1", "source_node_id": "start", "target_node_id": "child"},
        {"id": "p2", "source_node_id": "child", "target_node_id": "ok", "when": "done"},
        {"id": "p3", "source_node_id": "child", "target_node_id": "ko", "when": "blocked"},
    ]
    parent_key = await publish_phased(db, parent_definition)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    parent = await start_run(db, user=admin, workflow_key=parent_key, project_id=workspace_id, session=session)
    child_resolution = await run_turn_resolution(db, session, user_message="Go.")
    assert (parent.status, parent.waiting_kind) == ("waiting", "sub_workflow")
    child = await db.get(WorkflowRun, child_resolution["workflow_run"]["run_id"])
    assert child is not None and child.parent_run_id == parent.id
    await phase_turn(db, session.id, child_resolution, ["knowledge_search", "knowledge_read"])
    assert (child.status, child.outcome) == ("completed", "done")
    assert (parent.status, parent.outcome) == ("completed", "delivered")


@pytest.mark.asyncio
async def test_the_phased_editor_shows_the_graph_and_a_phase_opens_in_the_steps_canvas(client, auth_headers, db):
    from sqlalchemy import select

    from app.models import FlowDefinition

    key = await publish_phased(db, phased_definition(max_iterations=2))
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    view = (await client.get(f"/api/v1/phased-workflows/{flow.id}", headers=auth_headers)).json()
    assert [node["kind"] for node in view["nodes"]] == ["start", "phase", "gate", "outcome"]
    assert next(edge for edge in view["edges"] if edge["kind"] == "loop")["max_iterations"] == 2
    assert view["validation_report"]["valid"] is True

    phase = (await client.get(f"/api/v1/phased-workflows/{flow.id}/phases/work/graph", headers=auth_headers)).json()
    assert phase["phase"]["node_id"] == "work"
    assert [node["kind"] for node in phase["graph"]["nodes"]] == ["start", "check", "result"]
    nodes = [node for node in phase["graph"]["nodes"] if node["kind"] == "check"]
    nodes.append({"kind": "check", "check": {"type": "tool_called", "params": {"tools": ["knowledge_read"]},
                                             "blocking": False, "description": "Read a source"}})
    saved = await client.post(f"/api/v1/phased-workflows/{flow.id}/phases/work/graph", headers=auth_headers,
                              json={"base_version_id": phase["version_id"], "graph": {"nodes": nodes}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == phase["version"] + 1
    assert len([node for node in saved.json()["graph"]["nodes"] if node["kind"] == "check"]) == 2
    stale = await client.post(f"/api/v1/phased-workflows/{flow.id}/phases/work/graph", headers=auth_headers,
                              json={"base_version_id": phase["version_id"], "graph": {"nodes": nodes}})
    assert stale.status_code == 409
    overview = (await client.get("/api/v1/phased-workflows/overview", headers=auth_headers)).json()
    assert next(row for row in overview["flows"] if row["key"] == key)["execution_kind"] == "phased"
