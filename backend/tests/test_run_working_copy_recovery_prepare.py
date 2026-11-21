"""The server prepare step, the workspace sweeper, foreign clones, unready candidates, readers and logged connector failures during recovery."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.services.session.workspace import cleanup_expired_session_workspaces
from app.services.workflow_runs.records import main_session_id
from app.services.workflow_runs.runtime_target.switch import change_runtime
from app.services.workflow_runs.workspace.recovery import RECOVERY_KEY
from tests.run_working_copy_recovery_support import (  # noqa: F401
    SECRET,
    _events,
    _git,
    _git_stays_offline,
    _held_run,
    _origin,
    _provider_tool,
    _report,
    _resolution,
    _server_pipeline,
)


@pytest.mark.asyncio
async def test_the_server_prepare_step_recreates_a_missing_copy_too(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.workspace.preparation import prepare_workspace

    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    _admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone")
    node = (await graph_for_run(db, run)).nodes[run.current_node_id]

    outcome, _route = await prepare_workspace(db, run, node)

    assert outcome.ok, outcome.reason
    root = Path(run.context["local_path"])
    assert persistent.resolve() in root.parents and _git(root, "rev-parse", "HEAD") == base


@pytest.mark.asyncio
async def test_the_sweeper_keeps_an_open_runs_workspace_and_frees_it_when_the_run_ends(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")
    await change_runtime(db, run, user=admin, raw={"kind": "server"})
    session_dir = persistent / str(await main_session_id(db, run))
    old = time.time() - 30 * 24 * 3600
    os.utime(session_dir, (old, old))

    kept = await cleanup_expired_session_workspaces(db)
    assert session_dir.name in kept["skipped"] and session_dir.exists()

    run.status = "completed"
    await db.flush()
    os.utime(session_dir, (old, old))
    freed = await cleanup_expired_session_workspaces(db)
    assert session_dir.name in freed["deleted"] and not session_dir.exists()


@pytest.mark.asyncio
async def test_a_clone_that_is_not_the_runs_repository_is_refused(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin, remote="https://bitbucket.org/someone-else/other.git")
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert "not provably the run's repository" in _report(run)["detail"] and RECOVERY_KEY not in run.context
    assert not list(persistent.rglob("run-copies/*"))


@pytest.mark.parametrize("record", [
    {"evidence": {"work": {"tools": [{"name": "read_workspace_file", "succeeded": True},
                                     {"name": "write_workspace_file", "succeeded": True}], "turns": 1}}},
    {"evidence": {"work": {"tools": [{"name": "run_test_suite", "succeeded": True}], "turns": 1}}},
    {"tests": {"runs": [{"source": "chat", "results": []}]}},
    {"review": {"verdict": "pass"}},
    {"slices": {"s1": {"status": "merged"}}},
])
@pytest.mark.asyncio
async def test_recorded_local_work_or_tree_bound_evidence_is_never_recloned(db, tmp_path, monkeypatch, record):
    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone")
    run.context = {**run.context, **record}
    await db.flush()

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert calls == [] and RECOVERY_KEY not in run.context
    assert _report(run)["state"] == "recovery_unverified", _report(run)


@pytest.mark.asyncio
async def test_a_candidate_whose_environment_is_not_ready_is_never_taken_over(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.runtime_target import server_build
    from app.services.workflow_runs.workspace import server_prepare

    async def not_ready(root, environment):
        return {"state": "not_ready", "reason": "python3.12: command not found",
                "probes": [{"what": "python", "ok": False}]}

    monkeypatch.setattr(server_prepare, "prepare_environment", not_ready)
    # A workflow that tests: only then does the server prepare (and here fail) its test environment.
    monkeypatch.setattr(server_build, "builds_or_tests", lambda *args, **kwargs: True)
    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY not in run.context and run.context["local_path"] == str(tmp_path / "gone")
    assert not list(persistent.rglob("run-copies/*"))
    assert (await _resolution(db, run))["status"] == "held"


@pytest.mark.asyncio
async def test_a_reader_cannot_run_the_re_prepare(db, tmp_path, monkeypatch):
    import uuid

    from app.models import Project, User
    from app.services.workflow_runs import access
    from app.services.workflow_runs.access import require_run
    from app.services.workflow_runs.records import WorkflowRunError

    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    _admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                     recorded=tmp_path / "gone")
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    run.project_id = project.id
    name = f"reader-{uuid.uuid4().hex[:6]}"
    reader = User(id=str(uuid.uuid4()), username=name, email=f"{name}@example.test", password_hash="x")
    db.add(reader)
    await db.flush()

    async def in_scope(db_, user):  # the reader sees the run's Workspace
        return {project.id}

    monkeypatch.setattr(access, "work_scope_project_ids", in_scope)
    with pytest.raises(WorkflowRunError) as refused:
        await require_run(db, run.id, reader, write=True)  # the run-action route's gate

    assert refused.value.status_code == 403 and calls == [] and RECOVERY_KEY not in run.context


@pytest.mark.asyncio
async def test_a_secret_in_a_connector_failure_stays_out_of_the_logs(db, tmp_path, monkeypatch, caplog):
    import logging

    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin, fail=f"git clone https://x-token-auth:{SECRET}@bitbucket.org/x.git failed")
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone")

    with caplog.at_level(logging.DEBUG):
        await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert SECRET not in caplog.text
    assert SECRET not in json.dumps([run.context, [event.detail for event in await _events(db, run)]], default=str)
