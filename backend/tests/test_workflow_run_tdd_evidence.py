"""DevOps workflows S5: per-test results (chat, octryx-claude, CI) and the TDD checks red → green."""

from __future__ import annotations

import copy
import subprocess
import uuid
from types import SimpleNamespace

import pytest

from app.models import ToolCall
from app.services.workflow_checks.evidence import turn_evidence
from app.services.workflow_checks.library import TurnEvidence, evaluate_checks
from app.services.workflow_checks.test_results import parse_test_output
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.confirmation_payloads import contract_test_ids
from app.services.workflow_runs.gateway_tests import record_gateway_tests
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.test_runs import confirm_tests, gate_fields, snapshot_confirmed_tests
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PYTEST_RED = """tests/test_totals.py::test_rounds_half_up FAILED
tests/test_totals.py::test_zero PASSED
FAILED tests/test_totals.py::test_rounds_half_up - AssertionError: expected 3 got 2
"""
PYTEST_GREEN = "tests/test_totals.py::test_rounds_half_up PASSED\ntests/test_totals.py::test_zero PASSED\n"
JUNIT = """<?xml version="1.0"?><testsuite><testcase classname="TotalsTest" name="roundsHalfUp">
<failure message="expected 3"/></testcase><testcase classname="TotalsTest" name="boots"><error message="NoClass"/>
</testcase><testcase classname="TotalsTest" name="slow"><skipped/></testcase></testsuite>"""


def test_test_output_is_read_into_per_test_results():
    assert parse_test_output(PYTEST_RED) == {
        "tests/test_totals.py::test_rounds_half_up": {"outcome": "failed", "message": "AssertionError: expected 3 got 2"},
        "tests/test_totals.py::test_zero": {"outcome": "passed", "message": ""},
    }
    # A JUnit classname names a module, not a file: without the file it stays unresolved, never guessed.
    from app.services.workflow_checks.test_output import parse

    assert parse_test_output(JUNIT) == {}
    assert {item["raw"]: item["outcome"] for item in parse(JUNIT).unresolved} == {
        "TotalsTest.roundsHalfUp": "failed", "TotalsTest.boots": "error", "TotalsTest.slow": "skipped"}
    go = parse("--- FAIL: TestTotals (0.01s)\n--- PASS: TestZero")
    assert go.results == {} and go.unresolved[0]["raw"] == "TestTotals" and go.unresolved[0]["outcome"] == "failed"
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="x"/></testsuite>'
    assert parse_test_output(bomb) == {} and "declares entities" in parse(bomb).problems[0]
    assert contract_test_ids({"acceptance_criteria": [
        {"validation_commands": ["pytest -v tests/test_totals.py::test_rounds_half_up"]},
        {"validation_commands": ["go test ./pkg/totals_test.go"]}, {"tests": ["TotalsTest.roundsHalfUp"]},
    ]}) == ["tests/test_totals.py::test_rounds_half_up", "pkg/totals_test.go", "TotalsTest.roundsHalfUp"]


def _suite(stdout: str, *, green: bool) -> dict:
    return {"tool_name": "run_test_suite", "status": "success",
            "result": {"stdout": stdout, "exit_code": 0 if green else 1, "all_green": green}}


def test_tests_passed_works_in_chat_the_last_run_after_the_last_change_decides():
    edit = {"tool_name": "edit_workspace_file", "status": "success", "result": {}}
    check = [{"type": "test_command_passed", "params": {}, "blocking": True, "description": "tests"}]
    assert turn_evidence([edit]).verification_state == "no_test_after_last_change"
    assert evaluate_checks(check, turn_evidence([edit]))[0].outcome == "failed"
    assert evaluate_checks(check, turn_evidence([edit, _suite(PYTEST_GREEN, green=True)]))[0].outcome == "passed"
    assert turn_evidence([_suite(PYTEST_RED, green=False), edit, _suite(PYTEST_RED, green=False)]).verification_state == (
        "last_test_failed")
    assert turn_evidence([]).verification_state is None  # nothing changed: nothing to prove
    assert evaluate_checks(check, turn_evidence([]))[0].outcome == "not_applicable"


def _check(kind: str, **params) -> list[dict]:
    return [{"type": kind, "params": params, "blocking": True, "description": kind}]


def test_red_green_intact_reproduces_and_ci_green():
    confirmed = ["tests/test_totals.py::test_rounds_half_up"]
    red = {"results": parse_test_output(PYTEST_RED), "all_green": False}
    green = {"results": parse_test_output(PYTEST_GREEN), "all_green": True}
    evidence = lambda runs, **extra: TurnEvidence(test_runs=runs, confirmed_tests=confirmed, **extra)  # noqa: E731
    assert evaluate_checks(_check("tests_red"), evidence([red]))[0].outcome == "passed"
    assert evaluate_checks(_check("tests_red"), evidence([green]))[0].outcome == "failed"
    assert evaluate_checks(_check("tests_green"), evidence([red, green], red_seen=True))[0].outcome == "passed"
    never_red = evaluate_checks(_check("tests_green"), evidence([green]))[0]
    assert (never_red.outcome, never_red.detail) == ("failed", "the confirmed tests were never seen failing before "
                                                               "they passed")
    missing = {"results": {"tests/test_zero.py::test_zero": {"outcome": "passed", "message": ""}}, "all_green": True}
    assert evaluate_checks(_check("confirmed_tests_intact"), evidence([missing]))[0].outcome == "failed"
    assert evaluate_checks(_check("reproduces", symptom="expected 3"), evidence([red]))[0].outcome == "passed"
    assert evaluate_checks(_check("reproduces", symptom="timeout"), evidence([red]))[0].outcome == "failed"
    assert evaluate_checks(_check("ci_green"), TurnEvidence(ci_state="succeeded"))[0].outcome == "passed"
    assert evaluate_checks(_check("ci_green"), TurnEvidence())[0].outcome == "not_applicable"


def _tdd_definition() -> dict:
    write = copy.deepcopy(PHASE)
    write["workflow_contract"]["checks"] = [{"type": "tool_called", "params": {"tools": ["run_test_suite"]},
                                             "blocking": True, "description": "Tests ran"}]
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "tests", "type": "phase", "label": "Tests first", "config": copy.deepcopy(write)},
                  {"id": "red", "type": "gate", "config": {"checks": _check("tests_red")}},
                  {"id": "impl", "type": "phase", "label": "Implement", "config": copy.deepcopy(write)},
                  {"id": "green", "type": "gate", "config": {"checks": _check("tests_green")}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "tests"},
                  {"id": "2", "source_node_id": "tests", "target_node_id": "red"},
                  {"id": "3", "source_node_id": "red", "target_node_id": "impl", "when": "passed"},
                  {"id": "4", "source_node_id": "red", "target_node_id": "tests", "when": "failed", "kind": "loop",
                   "max_iterations": 2},
                  {"id": "5", "source_node_id": "impl", "target_node_id": "green"},
                  {"id": "6", "source_node_id": "green", "target_node_id": "done", "when": "passed"},
                  {"id": "7", "source_node_id": "green", "target_node_id": "impl", "when": "failed", "kind": "loop",
                   "max_iterations": 2}],
    }


async def _turn(db, session, output: str, *, green: bool) -> None:
    resolution = await run_turn_resolution(db, session, user_message="Work.")
    await phase_turn_with_history(db, session.id, resolution, [_suite(output, green=green)])


async def phase_turn_with_history(db, session_id, resolution, history):
    from tests.phase_turn_support import finish_phase_turn

    await finish_phase_turn(db, session_id, resolution, history)


@pytest.mark.asyncio
async def test_a_phased_run_goes_red_then_green_on_the_confirmed_tests(db, tmp_path):
    admin = await admin_user(db)
    key = await publish_phased(db, _tdd_definition())
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    test_file = tmp_path / "tests" / "test_totals.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_rounds_half_up():\n    assert total(2.5) == 3\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # the run's copy is a git working copy
    run.context = {**run.context, "local_path": str(tmp_path)}
    confirm_tests(run, ["tests/test_totals.py::test_rounds_half_up"])
    await snapshot_confirmed_tests(db, run)

    await _turn(db, session, PYTEST_GREEN, green=True)  # the test passes before any fix: not red
    assert (run.current_node_id, run.gate_results["red"]["state"]) == ("tests", "failed")
    await _turn(db, session, PYTEST_RED, green=False)
    assert run.current_node_id == "impl" and gate_fields(run)["red_seen"] is True

    # The forge: after red, the confirmed test is weakened; the suite turns "green".
    confirmed = test_file.read_text()
    test_file.write_text("def test_rounds_half_up():\n    assert True\n")
    await _turn(db, session, PYTEST_GREEN, green=True)
    assert run.gate_results["green"]["state"] == "failed" and run.current_node_id == "impl"
    assert "changed or was removed after it was confirmed" in run.gate_results["green"]["results"][0]["detail"]

    test_file.write_text(confirmed)  # the code is fixed instead: the confirmed test, unchanged, passes
    await _turn(db, session, PYTEST_GREEN, green=True)
    assert (run.status, run.outcome) == ("completed", "done")
    assert [entry["source"] for entry in run.context["tests"]["runs"]] == ["chat"] * 4
    _ = phase_turn


@pytest.mark.asyncio
async def test_tests_corrected_in_the_red_loop_are_the_ones_frozen_for_green(db, tmp_path):
    admin = await admin_user(db)
    key = await publish_phased(db, _tdd_definition())
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    test_file = tmp_path / "tests" / "test_totals.py"
    test_file.parent.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    run.context = {**run.context, "local_path": str(tmp_path)}
    confirm_tests(run, ["tests/test_totals.py::test_rounds_half_up"])
    test_file.write_text("def test_rounds_half_up():\n    assert total(2.5) == 3\n\n\n"
                         "def test_rounds_half_up():\n    assert total(2.5) == 3\n")  # a duplicated block
    await _turn(db, session, PYTEST_RED, green=False)
    assert run.current_node_id == "impl" and gate_fields(run)["red_seen"] is True

    # Back in tests-first (the Red loop): the duplicate is removed and the tests are red again.
    run.current_node_id = "tests"
    run.node_state = {**dict(run.node_state or {}), "node_id": "tests"}
    corrected = "def test_rounds_half_up():\n    assert total(2.5) == 3\n"
    test_file.write_text(corrected)
    await _turn(db, session, PYTEST_RED, green=False)
    assert run.current_node_id == "impl"

    # The implementation makes the corrected tests green; they are intact.
    await _turn(db, session, PYTEST_GREEN, green=True)
    assert (run.status, run.outcome) == ("completed", "done"), run.gate_results.get("green")

    # Frozen after tests-first: a change during implementation still fails green.
    assert run.context["confirmed_test_files"]["tests/test_totals.py::test_rounds_half_up"]["sha256"]


@pytest.mark.asyncio
async def test_octryx_test_calls_of_a_bound_session_become_test_runs(db):
    admin = await admin_user(db)
    key = await publish_phased(db, _tdd_definition())
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session)
    policy = SimpleNamespace(verification=SimpleNamespace(test_command_prefixes=[("pytest",)]))
    call = ToolCall(id=str(uuid.uuid4()), session_id=session.id, tool_name="Bash",
                    parameters={"command": "pytest -rA tests"}, status="success",
                    result={"is_error": True, "excerpt": PYTEST_RED})
    db.add(call)
    await db.flush()
    assert await record_gateway_tests(db, session_id=session.id, policy=policy, tool_calls=[call]) is True
    assert await record_gateway_tests(db, session_id=session.id, policy=policy, tool_calls=[call]) is False
    entry = run.context["tests"]["runs"][-1]
    assert entry["source"] == "octryx" and entry["results"]["tests/test_totals.py::test_rounds_half_up"]["outcome"] == (
        "failed")
    other = await new_chat_session(db, admin, None)
    assert await record_gateway_tests(db, session_id=other.id, policy=policy, tool_calls=[call]) is False


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
