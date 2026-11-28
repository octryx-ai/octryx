"""The commit trailer names every model the run used, and a pytest command that collected nothing is "no tests" unless a proof test was expected."""

from __future__ import annotations

import pytest

from app.models import Session, TurnTrace, WorkflowRun, WorkflowRunSession
from app.services.workflow_runs.platform import repo_ref
from tests.phased_workflow_fixtures import admin_user


@pytest.mark.asyncio
async def test_the_trailer_names_every_model_the_run_used(db):
    admin = await admin_user(db)
    run = WorkflowRun(title="x", workflow_kind="phased", workflow_key="team-delivery", status="running",
                      requested_by=admin.id, ticket_key="CHEF-2",
                      context={"runtime_target": {"kind": "device", "model": "claude-haiku-5-5"}})
    main, item = Session(user_id=admin.id, status="active"), Session(user_id=admin.id, status="active")
    db.add_all([run, main, item])
    await db.flush()
    db.add_all([WorkflowRunSession(run_id=run.id, session_id=main.id, role="main"),
                WorkflowRunSession(run_id=run.id, session_id=item.id, role="item", active=False)])
    for session, model in ((main, "claude-sonnet-5-5"), (item, "claude-haiku-5-5"), (main, "claude-sonnet-5-5")):
        db.add(TurnTrace(session_id=session.id, provider="device", model=model, input_messages_json=[],
                         context_snapshot_json={}, tool_trace_json=[], raw_output={}, usage_json={}))
        await db.flush()
    models = await repo_ref.run_models(db, run)
    assert sorted(models) == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    trailers = repo_ref.ai_trailers(run, None, models)
    assert trailers.count("AI-Generated-By-octryx:") == 2 and "claude-sonnet-5-5" in trailers
    assert repo_ref.ai_trailers(run, None, []) == "AI-Generated-By-octryx: claude-haiku-5-5\nOctryx-Run: CHEF-2"


def test_a_pytest_command_that_collected_nothing_is_no_tests():
    from app.services.workflow_runs.pipeline_results import _no_tests

    system = ".venv/bin/python -m pytest -v tests/system"
    assert _no_tests(system, 4, "ERROR: file or directory not found: tests/system\n\nno tests ran in 0.01s")
    assert _no_tests(system, 5, "collected 0 items\n\n=== no tests ran in 0.02s ===")
    assert not _no_tests(system, 4, "ERROR: usage: pytest [options] -- unrecognized arguments: --bad")
    assert not _no_tests(system, 1, "1 failed")
    assert not _no_tests("npm test", 5, "no tests ran")


@pytest.mark.asyncio
async def test_the_pipeline_is_green_without_tests_but_red_when_a_proof_was_expected(db, monkeypatch):
    from app.services.workflow_runs import pipeline_report

    admin = await admin_user(db)
    commands = ["pytest -q --ignore=tests/system", "pytest -v tests/system"]

    def run_with(tasks):
        run = WorkflowRun(title="x", workflow_kind="phased", workflow_key="k", status="waiting", requested_by=admin.id,
                          current_node_id="pipeline", node_state={"entry": 1},
                          context={"pipeline": {"state": "pending", "node_id": "pipeline", "entry": 1,
                                                "commands": commands}})
        if tasks:
            run.context = {**run.context, "task_list": tasks}
        return run

    routed = []

    async def route(_db, _run, outcome):
        routed.append(outcome)

    monkeypatch.setattr(pipeline_report, "_route", route)
    report = {"node_id": "pipeline", "entry": 1, "results": [
        {"command": commands[0], "exit_code": 0, "output_tail": "3 passed in 0.1s"},
        {"command": commands[1], "exit_code": 4, "output_tail": "ERROR: file or directory not found: tests/system"}]}
    run = run_with(None)
    db.add(run)
    await db.flush()
    assert await pipeline_report.record_report(db, run, report, session_id="s") == "green"
    assert run.context["pipeline"]["results"][1]["no_tests"] is True

    monkeypatch.setattr("app.services.workflow_runs.task_list.run_task_list", lambda _run: [
        {"id": "T1", "title": "shell", "status": "open", "proof": "tests/system/test_shell.py::test_opens"}])
    monkeypatch.setattr("app.services.workflow_runs.task_list.proofs_of", lambda task: [task["proof"]])
    monkeypatch.setattr("app.services.workflow_runs.task_list.unproven",
                        lambda tasks, seen: [f"{task['id']} ({task['proof']})" for task in tasks
                                             if task["proof"] not in seen])

    async def store(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.workflow_runs.task_status.store", store)
    monkeypatch.setattr("app.services.workflow_runs.task_status.after_pipeline", lambda tasks, *_a, **_k: tasks)
    expected = run_with(None)
    db.add(expected)
    await db.flush()
    assert await pipeline_report.record_report(db, expected, report, session_id="s") == "red"
    assert "missing proof tests" in routed[-1].reason and "tests/system failed" not in routed[-1].reason
