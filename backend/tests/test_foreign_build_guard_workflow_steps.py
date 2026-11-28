"""Workflow-run steps never build on the server copy (declared test and lint commands, workspace prepare), and what a device declares is not the server's."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE
from tests.phased_seed_definitions import seed_definitions

# --- workflow-run steps on the server --------------------------------------------------------------------------------

def test_the_declared_test_or_lint_command_is_refused_on_the_server_copy(tmp_path):
    from app.services.workflow_runs.workspace.declared_tests import not_ready_reason

    assert not_ready_reason("test", ".venv/bin/python -m pytest -q", tmp_path, {}, {}) == SERVER_BUILD_MESSAGE
    assert not_ready_reason("test", "mvn -q test", tmp_path, {}, {}) == SERVER_BUILD_MESSAGE
    assert not_ready_reason("lint", "npm run lint", tmp_path, {}, {}) == SERVER_BUILD_MESSAGE
    assert not_ready_reason("lint", "ruff check .", tmp_path, {}, {}) == ""  # a static linter still runs
    # ... but not from the working copy's own ``.venv/bin`` first on PATH: that ``ruff`` is a repository file.
    assert not_ready_reason("lint", "ruff check .", tmp_path, {"path": [".venv/bin"]}, {}) == SERVER_BUILD_MESSAGE


@pytest.mark.asyncio
async def test_workspace_prepare_never_runs_a_setup_install_on_the_server(tmp_path, monkeypatch):
    from app.services.workflow_runs.workspace import server_prepare

    spawned: list = []
    real_exec = server_prepare.asyncio.create_subprocess_exec

    async def spy(*argv, **kwargs):
        spawned.append(list(argv))
        return await real_exec(*argv, **kwargs)

    monkeypatch.setattr(server_prepare.asyncio, "create_subprocess_exec", spy)
    environment = {"probes": [{"what": "pytest", "shell": "test -d .venv"}],
                   "setup": ["python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt"]}
    report = await server_prepare.prepare_environment(Path(tmp_path), environment)
    assert report["state"] == "not_ready"
    assert report["setup"][0]["exit_code"] == server_prepare.REFUSED_EXIT
    assert report["setup"][0]["output"] == SERVER_BUILD_MESSAGE and SERVER_BUILD_MESSAGE in report["reason"]
    assert ["/bin/sh", "-c", "test -d .venv"] in spawned  # the read-only probe ran, no setup command did
    assert not [argv for argv in spawned if "venv .venv" in " ".join(argv) or "pip" in " ".join(argv)]




def test_the_shipped_workflows_that_build_and_those_that_only_read():
    from app.services.workflow_runs.runtime_target.server_build import build_steps

    steps = {seed["key"]: build_steps(seed["definition"]) for seed in seed_definitions()}
    assert steps["bug-fix-reproduction"][:3] == ["Reproduce", "Reproduces", "Minimal fix"]
    assert steps["feature-delivery-tdd"][:2] == ["Tests first", "Red"]
    assert steps["jira-intake-triage"] == steps["incident-analysis"] == []
    # A check that a tool is NOT called is no build.
    assert build_steps({"nodes": [{"id": "a", "type": "phase", "config": {"workflow_contract": {"checks": [
        {"type": "tool_not_called", "params": {"tools": ["run_test_suite"]}}]}}}]}) == []
