"""A parallel_work node publishes with its plan, roles and routes; replan must lead back to the plan, each role is validated like a phase, and a static fork is refused."""

from __future__ import annotations

from app.services.flow_definitions import validate_flow_definition
from tests.teamwork_engine_support import _role, team_definition


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_flow_definition(definition)["errors"]]


# --- publish validation ------------------------------------------------------------------------------------------


def test_a_parallel_work_node_publishes_with_its_plan_roles_and_routes():
    assert validate_flow_definition(team_definition())["valid"] is True
    assert validate_flow_definition(team_definition(parallel=False))["valid"] is True


def test_replan_must_be_a_way_back_to_the_plan():
    assert "parallel_routes" in _codes(team_definition(replan_kind="next"))
    missing_done = team_definition()
    missing_done["edges"] = [edge for edge in missing_done["edges"] if edge["id"] != "e3"]
    assert "parallel_routes" in _codes(missing_done)


def test_the_plan_is_a_phase_that_submits_the_work_plan():
    assert "parallel_plan" in _codes(team_definition(plan_output="test_contract"))


def test_each_role_is_validated_like_a_phase():
    broken = _role()
    broken.pop("workflow_contract")
    without_agent = _role()
    without_agent.pop("agent")
    codes = _codes(team_definition(roles={"backend": broken, "frontend": without_agent}))
    assert "phase_without_contract" in codes and "phase_without_agent" in codes
    assert "parallel_roles" in _codes(team_definition(roles={}))
    assert "parallel_roles" in _codes(team_definition(roles={"Back End": _role()}))


def test_a_static_fork_is_still_refused_and_points_to_parallel_work():
    forked = team_definition()
    forked["nodes"].append({"id": "other", "type": "outcome", "config": {"outcome": "blocked"}})
    forked["edges"].append({"id": "fork", "source_node_id": "plan", "target_node_id": "other"})
    errors = [error for error in validate_flow_definition(forked)["errors"] if error["code"] == "ambiguous_exit"]
    assert errors and "Parallel work" in errors[0]["message"]
