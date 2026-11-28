"""The repository's declared lint runs in the pipeline between the tests and the system test: red lint, red pipeline;
no declared lint, no step."""

from __future__ import annotations

import pytest

from app.services.workflow_runs import pipeline, pipeline_failure, pipeline_report
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import _at_pipeline, _report

pytestmark = pytest.mark.usefixtures("scripted_pool")

TEST = ".venv/bin/python -m pytest -q --ignore=tests/system"
LINT = ".venv/bin/ruff check ."
SYSTEM = ".venv/bin/python -m pytest -v tests/system"


@pytest.mark.asyncio
@pytest.mark.parametrize(("environment", "expected"), [
    ({"test": TEST, "lint": LINT, "system_test": SYSTEM}, ([TEST, LINT, SYSTEM], SYSTEM)),
    ({"test": TEST, "system_test": SYSTEM}, ([TEST, SYSTEM], SYSTEM)),
    ({"test": TEST, "lint": LINT}, ([TEST, LINT], "")),
])
async def test_the_declared_lint_is_a_pipeline_command_after_the_tests(monkeypatch, environment, expected):
    async def declared(_db, _run):
        return {**environment, "path": [".venv/bin"]}

    monkeypatch.setattr("app.services.workflow_runs.workspace.spec.environment_for_run", declared)
    commands, path, system = await pipeline.commands_for(None, None)
    assert (commands, system) == expected and path == [".venv/bin"]


@pytest.mark.asyncio
async def test_a_declared_green_lint_keeps_the_pipeline_green(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch, commands_declared=[TEST, LINT, SYSTEM])
    assert pipeline.contract_view(run)["commands"] == [TEST, LINT, SYSTEM]
    assert await pipeline_report.record_report(db, run, _report(run, [0, 0, 0]), session_id=session.id) == "green"


@pytest.mark.asyncio
async def test_a_declared_red_lint_makes_the_pipeline_red_and_names_it_to_the_agent(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch, commands_declared=[TEST, LINT, SYSTEM])
    assert await pipeline_report.record_report(db, run, _report(run, [0, 1, 0]), session_id=session.id) == "red"
    assert run.current_node_id == "work"
    assert [item["command"] for item in pipeline_failure.failure_for_agent(run)["failed"]] == [LINT]


@pytest.mark.asyncio
async def test_without_a_declared_lint_the_pipeline_has_no_lint_step(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch, commands_declared=[TEST, SYSTEM])
    assert pipeline.contract_view(run)["commands"] == [TEST, SYSTEM]
    assert await pipeline_report.record_report(db, run, _report(run, [0, 0]), session_id=session.id) == "green"
