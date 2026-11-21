"""The platform side of fail fast: a system test the device did not start after a red check is
neither green nor a failure of its own; the agent is told it is still due; and the pass's event says why it is red
(for example from its code style alone)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
from tests.workflow_run_pipeline_support import FILE, FILE_ENV, _at_file_pipeline, _file_report

ACCOUNT = {"file": FILE, "app_folder": "coffee/web/claude", "state": "ok", "sha256": "a" * 64,
           "environment": FILE_ENV, "commands": [FILE_ENV["test"], FILE_ENV["system_test"]]}


async def _reported(db, run) -> dict:
    await db.flush()
    events = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == pipeline.EVENT_REPORTED))).scalars().all()
    return events[-1].detail


@pytest.mark.asyncio
async def test_a_skipped_system_test_is_reported_as_not_run_and_never_as_a_failure(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    report = _file_report(run, ACCOUNT, (1,))
    report["results"].append({"command": FILE_ENV["system_test"], "skipped": "not run: an earlier check is red"})

    assert await pipeline_report.record_report(db, run, report, session_id=session.id) == "red"

    detail = await _reported(db, run)
    assert detail["commands"][1] == {"command": FILE_ENV["system_test"], "exit_code": None, "seconds": None,
                                     "skipped": "not run: an earlier check is red"}
    red = pipeline_failure.failure_for_agent(run)
    assert [item["command"] for item in red["failed"]] == [FILE_ENV["test"]]
    assert [item["command"] for item in red["not_run"]] == [FILE_ENV["system_test"]]
    assert "runs once the checks above and the code style are green" in red["not_run"][0]["reason"]


@pytest.mark.asyncio
async def test_a_pass_red_from_its_code_style_alone_says_so_in_its_event(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    monkeypatch.setattr(pipeline_report, "_style", lambda _current, _report: (["dart: format the changed test file"], []))

    assert await pipeline_report.record_report(db, run, _file_report(run, ACCOUNT, (0, 0)), session_id=session.id) == "red"

    detail = await _reported(db, run)
    assert [item["exit_code"] for item in detail["commands"]] == [0, 0]
    assert detail["code_style_errors"] == ["dart: format the changed test file"]


@pytest.mark.asyncio
async def test_the_style_question_before_the_system_test_is_judged_by_the_reports_rules(db, monkeypatch):
    """The same ``_style`` as the report decides; read only; another pass never
    blocks."""
    run, _session = await _at_file_pipeline(db, monkeypatch)
    current = pipeline.state(run)
    question = {"node_id": current["node_id"], "entry": current.get("entry"), "sizes": {"files": {}}}
    monkeypatch.setattr(pipeline_report, "_style", lambda _current, _report: (["lib/a.dart: format it"], ["old debt"]))
    assert pipeline_report.style_verdict(run, question) == {"blocking": True, "errors": ["lib/a.dart: format it"]}
    monkeypatch.setattr(pipeline_report, "_style", lambda _current, _report: ([], ["old debt only: a warning"]))
    assert pipeline_report.style_verdict(run, question) == {"blocking": False, "errors": []}
    assert pipeline_report.style_verdict(run, {**question, "entry": 99}) == {"blocking": False, "reason": "not_this_pass"}
    assert pipeline.state(run) == current  # nothing recorded
