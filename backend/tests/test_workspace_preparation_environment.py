"""Environment readiness: only a runner that executed tests is a test run, the environment declaration is validated, and a runner that cannot start pauses the run environment_not_ready without consuming a loop."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import WorkflowRun
from app.services.workflow_checks.test_command_outcome import ENVIRONMENT, NOT_RUN, RAN, classify
from app.services.workflow_runs.workspace.spec import derive_from_ci, probes, validate_environment
from app.time_utils import utc_now
from tests.device_job_session_parity_support import CONFIRMED, _call
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture
from tests.workspace_preparation_support import _device_at_tests_first, _server_pipeline, _stop  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")

NOT_INSTALLED = "Exit code 1\n/usr/bin/python3: No module named pytest"


NOT_FOUND = "Exit code 127\n(eval):1: command not found: pytest"


# --- the test command's outcome (pure) ---------------------------------------------------------------------------


def test_only_a_runner_that_executed_tests_is_a_test_run():
    assert classify({"excerpt": NOT_FOUND}, command="pytest tests/").kind == ENVIRONMENT
    missing = classify({"excerpt": NOT_INSTALLED}, command="python3 -m pytest tests/")
    assert (missing.kind, missing.exit_code) == (ENVIRONMENT, 1)
    assert "not installed" in missing.reason and "No module named pytest" in missing.reason
    assert classify({"stderr": "zsh: no such file or directory: .venv/bin/pytest", "exit_code": 127},
                    command=".venv/bin/pytest").kind == ENVIRONMENT
    assert classify({"excerpt": "Exit code 4\nImportError while loading conftest '/r/tests/conftest.py'."},
                    command="pytest").kind == ENVIRONMENT
    # A test module that cannot be collected (TDD: it imports what does not exist yet) ran no test: the agent's.
    collection = ("Exit code 2\n==== ERRORS ====\n___ ERROR collecting tests/test_slug.py ___\n"
                  "ModuleNotFoundError: No module named 'textkit.slug'\n!!! Interrupted: 1 error during collection !!!")
    assert classify({"excerpt": collection}, command="python3 -m pytest tests/").kind == NOT_RUN
    assert classify({"excerpt": "Exit code 5\ncollected 0 items\n\nno tests ran in 0.01s"},
                    command="pytest").kind == NOT_RUN
    assert classify({"excerpt": "Exit code 1\n1 failed, 2 passed in 0.12s"}, command="pytest").kind == RAN
    assert classify({"excerpt": "anything"}, command="pytest", parsed_results=3).kind == RAN
    assert classify({"stdout": "Ran 4 tests in 0.002s\n\nOK", "exit_code": 0}, command="python -m unittest").kind == RAN


def test_a_chat_test_run_whose_runner_is_missing_is_no_test_run_but_the_environments_failure():
    from app.services.workflow_checks.evidence import turn_evidence
    from app.services.workflow_checks.library import evaluate_checks

    missing = {"tool_name": "run_test_suite", "status": "success", "result": {
        "command": "python3 -m pytest tests/", "exit_code": 1, "stdout": "",
        "stderr": "/usr/bin/python3: No module named pytest", "all_green": False}}
    evidence = turn_evidence([missing])
    assert evidence.environment_failure["kind"] == "environment" and not evidence.test_runs
    called = [{"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "blocking": True}]
    assert evaluate_checks(called, evidence)[0].outcome == "failed"
    ran = {**missing, "result": {**missing["result"], "stdout": "tests/test_a.py::test_a FAILED\n1 failed in 0.1s",
                                 "stderr": ""}}
    later = turn_evidence([missing, ran])
    assert later.environment_failure is None and len(later.test_runs) == 1
    assert evaluate_checks(called, later)[0].outcome == "passed"


def test_the_environment_declaration_is_validated_and_ci_gives_a_proposal_only():
    declared, errors = validate_environment({
        "setup": ["python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt pytest flake8"],
        "test": "python -m pytest -v tests/ --junitxml=test-reports/report.xml", "lint": "flake8 .",
        "path": [".venv/bin"]})
    assert errors == [] and declared["path"] == [".venv/bin"]
    assert [probe["what"] for probe in probes(declared)] == ["test: python -m pytest", "lint: flake8"]
    _, refused = validate_environment({"setup": ["sudo pip install pytest"], "test": "pytest", "path": ["/usr/bin"]})
    assert any("sudo" in error for error in refused) and any("path entries" in error for error in refused)
    _, refused = validate_environment({"setup": ["pip install --user pytest"], "test": "pytest"})
    assert refused
    pipelines = ("image: python:3.11\npipelines:\n  default:\n    - step:\n        script:\n"
                 "          - pip install -r requirements.txt\n          - pip install pytest flake8\n"
                 "          - flake8 .\n          - python -m pytest -v tests/ --junitxml=test-reports/report.xml\n")
    derived = derive_from_ci({"bitbucket-pipelines.yml": pipelines})
    assert derived["source"] == "ci_derived" and derived["lint"] == "flake8 ."
    assert derived["setup"] == ["python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt",
                                ".venv/bin/pip install pytest flake8"]
    assert derived["test"] == "python -m pytest -v tests/ --junitxml=test-reports/report.xml"


# --- a runner that could not start pauses the run; no loop is consumed --------------------------------------------


@pytest.mark.asyncio
async def test_a_test_runner_that_cannot_start_pauses_environment_not_ready_without_consuming_a_loop(
        client, auth_headers, db, systems):  # noqa: F811
    run_id, working_copy, gateway, policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    entry = (await db.get(WorkflowRun, run_id)).node_state["entry"]
    test_path = str(working_copy / CONFIRMED)
    at = utc_now() + timedelta(seconds=5)
    answer = await _stop(db, gateway, policy, [
        _call(gateway, "Write", at=at, file_path=test_path),
        _call(gateway, "Bash", at=at + timedelta(seconds=1), ok=False, command=f"pytest {CONFIRMED}",
              excerpt=NOT_FOUND),
        _call(gateway, "Bash", at=at + timedelta(seconds=2), ok=False, command=f"python3 -m pytest {CONFIRMED}",
              excerpt=NOT_INSTALLED)])
    assert (answer["state"], answer["reason"]) == ("not_applicable", "workflow_run_paused"), answer
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "environment_not_ready", "tests_first")
    pause = run.node_state["pause"]
    assert "No module named pytest" in pause["message"] and f"python3 -m pytest {CONFIRMED}" in pause["message"]
    assert "red" not in dict(run.gate_results or {}) and "tests_first" not in dict(run.gate_results or {})
    assert run.loop_counters["loop-red"]["used"] == 0
    assert not dict(run.context.get("tests") or {}).get("runs")  # no test run was recorded
    assert dict(run.context.get("device_continuation") or {}).get("state") != "pending"
    actions = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["actions"]
    retry = next(item for item in actions if item["key"] == "continue")
    assert retry["label"] == "Retry after fixing the environment"

    # Retry after the fix: a new pass through Tests first, still no loop iteration used.
    retried = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "continue"})
    assert retried.status_code == 200, retried.text
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "tests_first")
    assert run.node_state["entry"] > entry and run.loop_counters["loop-red"]["used"] == 0


@pytest.mark.asyncio
async def test_a_collection_error_is_not_a_test_run_and_does_not_pause(client, auth_headers, db, systems):  # noqa: F811
    run_id, working_copy, gateway, policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    at = utc_now() + timedelta(seconds=5)
    collection = ("Exit code 2\n___ ERROR collecting tests/test_totals.py ___\nImportError: cannot import name "
                  "'round_total'\n!!! Interrupted: 1 error during collection !!!")
    answer = await _stop(db, gateway, policy, [
        _call(gateway, "Write", at=at, file_path=str(working_copy / CONFIRMED)),
        _call(gateway, "Bash", at=at + timedelta(seconds=1), ok=False, command=f"pytest {CONFIRMED}",
              excerpt=collection)])
    assert answer["state"] == "blocked" and "The test suite ran" in answer["detail"], answer
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "tests_first")
    assert run.loop_counters["loop-red"]["used"] == 0 and "red" not in dict(run.gate_results or {})
