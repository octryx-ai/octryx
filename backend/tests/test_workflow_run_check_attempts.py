from __future__ import annotations

import pytest

from app.models import Project
from app.services.devices.device_runs_keys import DEFAULTS, DeviceRunsPolicyError, normalize_device_runs
from app.services.devices.workspace_policy import set_workspace_device_runs
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.check_attempts import attempts_from, failed_checks, leaves_a_check
from app.services.workflow_runs.graph import PhasedEdge, PhasedGraph, PhasedNode
from app.services.workflow_runs.views import run_view
from tests.phased_workflow_fixtures import admin_user, phased_definition
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_failure_path import _session
from tests.test_workflow_run_pause import _turn
from tests.test_workflow_run_platform_actions import _run

pytestmark = pytest.mark.usefixtures("scripted_pool")

RED = ["knowledge_search"]


async def _red_rounds(db, session_id, count: int) -> None:
    for _ in range(count):
        await _turn(db, session_id, RED)


@pytest.mark.asyncio
async def test_a_red_check_goes_back_three_times_then_stops_in_checks_failed_with_the_output(db):
    run = await _run(db, phased_definition(max_iterations=10))
    session_id = await _session(db, run)

    await _red_rounds(db, session_id, DEFAULTS["check_attempts"])
    assert run.status == "running" and run.loop_counters["rework"]["used"] == DEFAULTS["check_attempts"]
    await _turn(db, session_id, RED)

    assert (run.status, run.pause_reason) == ("paused", "checks_failed")
    pause = run.node_state["pause"]
    assert pause["checks"] == [{"check": "tool_called", "detail": pause["checks"][0]["detail"]}]
    assert "failed 3 of 3 attempts" in pause["message"]
    view = await run_view(db, run, access="write", user=await admin_user(db))
    assert {action["key"] for action in view["actions"]} >= {"continue", "change_plan"}


@pytest.mark.asyncio
async def test_granting_one_more_attempt_continues_and_the_setting_no_longer_binds_that_loop(db):
    run = await _run(db, phased_definition(max_iterations=10))
    session_id = await _session(db, run)
    await _red_rounds(db, session_id, DEFAULTS["check_attempts"] + 1)
    assert run.pause_reason == "checks_failed"

    await perform_action(db, run, user=await admin_user(db), body={"action": "continue", "k": 1})
    assert run.status == "running" and run.loop_counters["rework"]["limit"] == DEFAULTS["check_attempts"] + 1

    await _turn(db, session_id, RED)
    assert (run.status, run.pause_reason) == ("paused", "loop_limit")


@pytest.mark.asyncio
async def test_the_workspace_setting_sets_the_attempts_and_the_workflow_limit_still_binds_below_it(db):
    run = await _run(db, phased_definition(max_iterations=10))
    await set_workspace_device_runs(db, project=await db.get(Project, run.project_id), patch={"check_attempts": 1},
                                    actor_id=(await admin_user(db)).id)
    session_id = await _session(db, run)
    await _red_rounds(db, session_id, 2)
    assert (run.status, run.pause_reason) == ("paused", "checks_failed")

    low = await _run(db, phased_definition(max_iterations=1))
    low_session = await _session(db, low)
    await _red_rounds(db, low_session, 2)
    assert (low.status, low.pause_reason) == ("paused", "loop_limit")


@pytest.mark.parametrize(("raw", "expected"), [
    (None, 3), ({}, 3), ({"check_attempts": 5}, 5), ({"check_attempts": 0}, 3), ({"check_attempts": "4"}, 3),
])
def test_attempts_come_from_the_workspace_device_runs_policy(raw, expected):
    assert DEFAULTS["check_attempts"] == 3 and attempts_from(raw) == expected


@pytest.mark.parametrize("bad", [0, 21, "3", True])
def test_the_policy_refuses_attempts_outside_one_to_twenty(bad):
    with pytest.raises(DeviceRunsPolicyError) as refused:
        normalize_device_runs({"check_attempts": bad}, "p")
    assert (refused.value.reason, refused.value.path) == ("invalid_number", "p.check_attempts")


def _graph(source: PhasedNode) -> PhasedGraph:
    return PhasedGraph(nodes={source.id: source}, edges=[])


def _loop(source: str, when: str | None = "failed") -> PhasedEdge:
    return PhasedEdge(id="back", source=source, target="work", kind="loop", when=when, max_iterations=5, title="")


@pytest.mark.parametrize(("node", "when", "expected"), [
    (PhasedNode("verify", "gate", "", {}), "failed", True),
    (PhasedNode("pipe", "platform_action", "", {"action": "pipeline.run"}), "red", True),
    (PhasedNode("ticket", "platform_action", "", {"action": "jira.comment"}), "failed", False),
    (PhasedNode("review", "review", "", {}), "changes_requested", False),
    (PhasedNode("review", "review", "", {}), "ci.failed", True),
])
def test_only_loops_leaving_a_check_are_bounded_by_the_attempts(node, when, expected):
    assert leaves_a_check(_graph(node), _loop(node.id, when)) is expected


def test_a_red_pipeline_names_its_failed_commands_and_their_output():
    class Run:
        gate_results: dict = {}
        context = {"pipeline": {"state": "red", "node_id": "pipe", "results": [
            {"command": "pytest", "exit_code": 1, "failed_tests": ["tests/test_a.py::test_x"], "output_tail": "E  1"},
            {"command": "ruff check .", "exit_code": 0, "output_tail": ""},
        ]}}

    assert failed_checks(Run(), "pipe") == [
        {"check": "pipeline", "detail": "pytest failed (tests/test_a.py::test_x)", "output_tail": "E  1"}]
