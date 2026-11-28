"""The environment file pipeline: exactly the file's commands with an audit, record pipelines, and invalid, refused, revalidated or missing files."""

from __future__ import annotations

import pytest

from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import (
    COMMANDS,
    FILE,
    FILE_ENV,
    _at_file_pipeline,
    _at_pipeline,
    _file_report,
    _report,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


def pipeline_format():
    from app.services.workflow_runs.workspace.spec import ENVIRONMENT_FILE_FORMAT

    return ENVIRONMENT_FILE_FORMAT


@pytest.mark.asyncio
async def test_the_environment_file_pipeline_runs_exactly_the_files_commands_and_keeps_the_audit(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    view = pipeline.contract_view(run)
    assert view["commands"] == [] and view["environment_file"] == {"file": FILE, "app_folder": "coffee/web/claude"}
    commands = [FILE_ENV["test"], FILE_ENV["system_test"]]
    account = {"file": FILE, "app_folder": "coffee/web/claude", "state": "ok", "sha256": "f" * 64,
               "environment": FILE_ENV, "commands": commands}
    assert await pipeline_report.record_report(db, run, _file_report(run, account, (0, 0)), session_id=session.id) == "green"
    audit = pipeline.state(run)["audit"]
    assert audit["commands"] == commands and audit["file"] == FILE and audit["sha256"] == "f" * 64
    assert audit["head"] == "a" * 40 and audit["source"] == "environment_file"
    assert pipeline.run_view(run)["audit"] == audit
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    reported = [event for event in events if event.kind == "pipeline_reported"][-1]
    assert reported.detail["audit"]["file"] == FILE and reported.detail["audit"]["commands"] == commands


@pytest.mark.asyncio
async def test_a_record_pipeline_still_names_its_commands_and_commit(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    report = {**_report(run, [0, 0]), "head": "b" * 40}
    assert await pipeline_report.record_report(db, run, report, session_id=session.id) == "green"
    assert pipeline.state(run)["audit"] == {"source": "repository_record", "commands": COMMANDS, "head": "b" * 40}


@pytest.mark.asyncio
async def test_an_invalid_or_refused_environment_file_goes_back_to_the_agent(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    account = {"file": FILE, "app_folder": "coffee/web/claude", "state": "invalid",
               "errors": ["'sudo apt-get install x' is refused: it installs outside the repository folder"]}
    assert await pipeline_report.record_report(db, run, _file_report(run, account), session_id=session.id) == "red"
    assert run.current_node_id == "work"
    red = pipeline_failure.failure_for_agent(run)
    assert red["environment_file"]["state"] == "invalid" and "refused" in red["environment_file"]["errors"][0]
    assert red["environment_file"]["format"] == pipeline_format()


@pytest.mark.asyncio
async def test_the_server_validates_the_reported_file_again(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    bad = {**FILE_ENV, "setup": ["npm install -g playwright"]}
    account = {"file": FILE, "app_folder": "coffee/web/claude", "state": "ok", "environment": bad,
               "commands": [bad["test"], bad["system_test"]]}
    assert await pipeline_report.record_report(db, run, _file_report(run, account, (0, 0)), session_id=session.id) == "red"
    assert "refused" in pipeline_failure.failure_for_agent(run)["environment_file"]["errors"][0]


@pytest.mark.asyncio
async def test_a_missing_environment_file_tells_the_agent_to_create_it(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    account = {"file": FILE, "app_folder": "coffee/web/claude", "state": "missing"}
    assert await pipeline_report.record_report(db, run, _file_report(run, account), session_id=session.id) == "red"
    red = pipeline_failure.failure_for_agent(run)
    assert red["note"].startswith(f"The pipeline found no {FILE} in your change. Create it")
    assert "runs exactly those in coffee/web/claude/" in red["note"]
