"""DevOps workflows S2: "Runs in phases" — the bounded state machine, its validation and its runtime gates."""

from __future__ import annotations

import copy

import pytest

from app.models import WorkflowRun
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.path_rules import blocked_paths, phase_path_outcomes
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


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
