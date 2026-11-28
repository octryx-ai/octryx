"""A merged reproduce+fix turn reaches its green gate: the platform confirms the submitted reproduction itself,
the confirmed tests' red is the class's red_on_base, and a failed gate's event names the failed checks."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.gate_evaluation import _evaluate_gate
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.test_runs import confirmed_tests, record_turn_test_runs
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.server_build_lock import lift_server_build_lock
from tests.test_workflow_run_hitl import _start
from tests.test_workflow_size_class_merge import MERGE, _definition

pytestmark = pytest.mark.usefixtures("scripted_pool")

PYTHON_TEST = "e2e/python/tests/test_split.py::test_shares_add_up_to_the_total"
GREEN = [{"type": "tests_green", "params": {}, "blocking": True, "description": "Green after red"},
         {"type": "confirmed_tests_intact", "params": {}, "blocking": True, "description": "Intact"}]


def _device_run(monkeypatch) -> None:
    from app.services.workflow_runs import test_runs

    lift_server_build_lock(monkeypatch)

    async def on_device(_db, _run):
        return True

    monkeypatch.setattr(test_runs, "device_run", on_device)


def _with_green_gate(classes: dict) -> dict:
    definition = copy.deepcopy(_definition(classes))
    definition["nodes"].insert(-1, {"id": "green", "type": "gate", "config": {"phase": "make", "checks": GREEN}})
    for edge in definition["edges"]:
        if edge["source_node_id"] == "make":
            edge["target_node_id"] = "green"
    definition["edges"].append({"id": "e8", "source_node_id": "green", "target_node_id": "fine", "when": "passed"})
    definition["edges"].append({"id": "e9", "source_node_id": "green", "target_node_id": "make", "when": "failed",
                                "kind": "loop", "max_iterations": 3})
    return definition


def _launcher_reports_the_file(run) -> None:
    from app.services.workflow_runs.octryx.facts import record_facts

    entry = dict(run.node_state or {}).get("entry")
    assert record_facts(run, {"node_id": "make", "entry": entry, "checked_files": [PYTHON_TEST.split("::")[0]],
                              "confirmed_test_digests": {PYTHON_TEST.split("::")[0]: "sha256:" + "a" * 64}})


def _run_of(outcome: str) -> dict:
    return {"source": "octryx", "all_green": outcome == "passed",
            "results": {PYTHON_TEST: {"outcome": outcome, "message": "assert 9.99 == 10.0" if outcome == "failed"
                                      else ""},
                        "e2e/python/tests/test_cli.py::test_help": {"outcome": "passed", "message": ""}}}


@pytest.mark.asyncio
async def test_a_merged_turn_confirms_its_reproduction_and_passes_green(db, monkeypatch):
    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_green_gate(MERGE))
    assert run.current_node_id == "make"
    answer = await submit_output(db, run, "submit_reproduction", {"tests": [PYTHON_TEST], "symptom": "9.99 != 10.0"})
    assert answer["state"] == "recorded", answer
    assert confirmed_tests(run) == [PYTHON_TEST]
    _launcher_reports_the_file(run)
    await record_turn_test_runs(db, run, [_run_of("passed")], node_id="make")
    graph = await graph_for_run(db, run)
    await _evaluate_gate(db, run, graph.nodes["green"])
    results = run.gate_results["green"]["results"]
    assert run.gate_results["green"]["state"] == "passed", [(item["type"], item["detail"]) for item in results]


@pytest.mark.asyncio
async def test_a_newer_submission_in_the_merge_rebinds_and_a_failed_gate_says_why(db, monkeypatch):
    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_green_gate(MERGE))
    await submit_output(db, run, "submit_reproduction", {"tests": ["e2e/python/tests/test_old.py::test_x"],
                                                         "symptom": "x"})
    await submit_output(db, run, "submit_reproduction", {"tests": [PYTHON_TEST], "symptom": "9.99 != 10.0"})
    assert confirmed_tests(run) == [PYTHON_TEST]
    _launcher_reports_the_file(run)
    await record_turn_test_runs(db, run, [_run_of("failed")], node_id="make")
    await _evaluate_gate(db, run, (await graph_for_run(db, run)).nodes["green"])
    event = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "gate_evaluated"))).scalars().all()[-1]
    assert event.detail["state"] == "failed"
    assert "tests_green" in [item["type"] for item in event.detail["failed"]]
    assert all(item["detail"] for item in event.detail["failed"])


@pytest.mark.asyncio
async def test_without_the_merge_green_still_needs_the_red_it_saw(db, monkeypatch):
    from app.services.workflow_runs.test_runs import confirm_tests, gate_fields

    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_green_gate({}))
    confirm_tests(run, [PYTHON_TEST])
    await record_turn_test_runs(db, run, [_run_of("passed")], node_id="make")
    assert gate_fields(run)["red_seen"] is False


def _base_output(name: str, word: str) -> str:
    return "\n".join(["============ test session starts ============", f"tests/test_split.py::{name} {word}",
                      "====== 1 failed in 0.1s ======"])


@pytest.mark.asyncio
async def test_a_weakened_resubmission_is_judged_on_its_latest_state_by_the_base_run(db, monkeypatch):
    from app.services.workflow_runs.red_on_base import judge, request

    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_green_gate(MERGE))
    run.context = {**dict(run.context or {}), "base_sha": "b" * 40, "app": {"path": "e2e/python"}}
    await submit_output(db, run, "submit_reproduction", {"tests": [PYTHON_TEST], "symptom": "9.99 != 10.0"})
    weakened = "e2e/python/tests/test_split.py::test_shares_are_numbers"
    await submit_output(db, run, "submit_reproduction", {"tests": [weakened], "symptom": "none"})
    asked = request(run, "e2e/python")
    assert asked["tests"] == ["tests/test_split.py::test_shares_are_numbers"]
    report = {"command": "python3 -m pytest -v tests/test_split.py", "exit_code": 0,
              "output_tail": _base_output("test_shares_are_numbers", "PASSED")}
    assert judge(asked, report) == [
        "tests/test_split.py::test_shares_are_numbers passes on the base commit: it does not reproduce the bug"]


@pytest.mark.asyncio
async def test_no_proof_no_push_the_pipeline_says_what_is_missing_and_the_pr_waits(db, monkeypatch):
    from app.services.workflow_runs.red_on_base import record
    from app.services.workflow_runs.red_on_base_proof import evidence_text, missing, unproven

    _device_run(monkeypatch)
    _admin, run, _session = await _start(db, _with_green_gate(MERGE))
    assert "submit_reproduction" in missing(run, None)[0]
    assert unproven(run).startswith("the reproduction is not proven") and evidence_text(run) == ""
    asked = {"base": "b" * 40, "tests": ["tests/test_split.py::test_shares_add_up_to_the_total"],
             "files": ["tests/test_split.py"]}
    record(run, asked, {"command": "python3 -m pytest -v tests/test_split.py", "exit_code": 1,
                        "output_tail": _base_output("test_shares_add_up_to_the_total", "FAILED")},
           node_id="pipeline", entry=3)
    assert missing(run, asked) == [] and unproven(run) == ""
    assert "`tests/test_split.py::test_shares_add_up_to_the_total`: failed on the base commit `bbbbbbbbbb`" in (
        evidence_text(run))
