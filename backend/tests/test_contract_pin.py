"""The run's environment file is its contract, pinned at preparation, so an agent that rewrites environment.json
cannot make the platform judge against the rewritten file."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs import pipeline, pipeline_report
from app.services.workflow_runs.workspace import contract_pin
from app.services.workflow_runs.workspace.preparation import file_commands
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import FILE, FILE_ENV, _at_file_pipeline, _file_report

pytestmark = pytest.mark.usefixtures("scripted_pool")

ORIGINAL = {**FILE_ENV, "serve": {"command": "python3 -m http.server 8090", "url": "http://127.0.0.1:8090/"}}
REWRITTEN = {"test": "true", "system_test": "true"}  # what an agent might bend it to


def _prep(environment: dict, sha: str) -> dict:
    return {"environment": {"state": "environment_file", "environment_file": {
        "file": FILE, "app_folder": "coffee/web/claude", "state": "ok", "sha256": sha, "environment": environment,
        "commands": {key: environment[key] for key in ("test", "system_test") if environment.get(key)}}}}


async def _events(db, run, kind):
    await db.flush()
    return (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind))).scalars().all()


@pytest.mark.asyncio
async def test_the_first_account_is_the_contract_and_a_rewritten_file_never_replaces_it(db, monkeypatch):
    run, _session = await _at_file_pipeline(db, monkeypatch)
    await contract_pin.from_preparation(db, run, _prep(ORIGINAL, "a" * 64))
    await contract_pin.from_preparation(db, run, _prep(REWRITTEN, "b" * 64))
    assert contract_pin.pin(run)["sha256"] == "a" * 64
    environment = file_commands({"source": "environment_file", "environment_file": FILE},
                                _prep(REWRITTEN, "b" * 64), run)
    assert (environment["test"], environment["system_test"]) == (FILE_ENV["test"], FILE_ENV["system_test"])
    [ignored] = await _events(db, run, "contract_change_ignored")
    assert (ignored.detail["from"], ignored.detail["to"]) == ("a" * 64, "b" * 64)
    served = pipeline.contract_view(run)["environment_pin"]["environment"]["serve"]
    assert (served["command"], served["url"]) == (ORIGINAL["serve"]["command"], ORIGINAL["serve"]["url"])


@pytest.mark.asyncio
async def test_a_pipeline_that_ran_a_rewritten_file_is_red_not_green(db, monkeypatch):
    run, session = await _at_file_pipeline(db, monkeypatch)
    await contract_pin.from_preparation(db, run, _prep(ORIGINAL, "a" * 64))
    account = {"file": FILE, "app_folder": "coffee/web/claude", "state": "ok", "sha256": "b" * 64,
               "environment": REWRITTEN, "commands": ["true", "true"]}
    assert await pipeline_report.record_report(db, run, _file_report(run, account, (0, 0)), session_id=session.id) == "red"
    assert pipeline.state(run)["audit"]["file_state"] == "contract_changed"


@pytest.mark.asyncio
async def test_only_a_node_that_allows_it_changes_the_contract_and_the_change_is_flagged(db, monkeypatch):
    run, _session = await _at_file_pipeline(db, monkeypatch)
    await contract_pin.from_preparation(db, run, _prep(ORIGINAL, "a" * 64))

    async def allowed(_db, _run):
        return True

    monkeypatch.setattr(contract_pin, "_allowed_here", allowed)  # config.allow_contract_change: true
    await contract_pin.from_preparation(db, run, _prep({**ORIGINAL, "lint": "ruff check ."}, "c" * 64))
    assert contract_pin.pin(run)["sha256"] == "c" * 64
    assert run.context[contract_pin.CHANGES_KEY][-1]["to"] == "c" * 64
    assert len(await _events(db, run, "contract_changed")) == 1


def test_the_tool_policy_refuses_an_edit_of_the_pinned_file_unless_the_node_allows_it():
    from app.services.workflow_runs.octryx.phase_rules import _path_decision

    phase = {"title": "Implement", "contract_file": FILE, "allow_contract_change": False,
             "path_rules": {"write": [], "create": [], "protect_confirmed_tests": False}, "protected_files": []}
    edit = {"file_path": f"/repo/{FILE}"}
    refused = _path_decision(phase, edit, "/repo", "/repo", {"target_exists": True, "shadows_installed": False})
    assert refused is not None and refused.reason == "protected_path" and "its contract" in refused.message
    assert "Next:" in refused.message
    assert _path_decision({**phase, "allow_contract_change": True}, edit, "/repo", "/repo",
                          {"target_exists": True, "shadows_installed": False}) is None
