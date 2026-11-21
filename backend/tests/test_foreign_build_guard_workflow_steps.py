"""Workflow-run steps never build on the server copy (declared test and lint commands, workspace prepare, SCIP indexers), and what a device declares is not the server's."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE, SERVER_BUILD_NOT_ALLOWED
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


def test_scip_indexers_driven_by_a_build_are_skipped(tmp_path):
    from app.services.code_intelligence.semantic_build import _plan_scip_command

    (tmp_path / "pom.xml").write_text("<project/>")
    for language in ("java", "c", "cpp"):
        plan = _plan_scip_command(repository_id="r", repo_root=tmp_path, language=language)
        assert (plan["status"], plan["reason"]) == ("skipped", SERVER_BUILD_NOT_ALLOWED), language


# --- what runs on a device is not the server's ------------------------------------------------------------------------

def test_only_a_server_runtime_is_held():
    from app.services.workflow_runs.runtime_target.server_build import runs_on_server, server_build_refusal

    definition = next(seed["definition"] for seed in seed_definitions() if seed["key"] == "feature-delivery-tdd")
    device = {"kind": "device", "device_id": "d1", "folder": "/Users/dev/pay", "profile": "governed"}
    device_thread = SimpleNamespace(metadata_={"execution_target": {**device}})
    assert runs_on_server({"kind": "server"}) and runs_on_server(None)
    assert not runs_on_server(device) and not runs_on_server({"kind": "terminal"})
    assert not runs_on_server(None, device_thread)  # a run without a target on a device thread runs there
    assert server_build_refusal(device, definition=definition) is None
    assert server_build_refusal({"kind": "terminal"}, definition=definition) is None
    message, steps = server_build_refusal({"kind": "server"}, definition=definition)
    assert "Tests first" in steps and "Implement" in steps
    assert message.startswith("This workflow builds or tests the repository (") and "Run it on your Mac" in message


def test_the_shipped_workflows_that_build_and_those_that_only_read():
    from app.services.workflow_runs.runtime_target.server_build import build_steps

    steps = {seed["key"]: build_steps(seed["definition"]) for seed in seed_definitions()}
    assert steps["bug-fix-reproduction"][:3] == ["Reproduce", "Reproduces", "Minimal fix"]
    assert steps["feature-delivery-tdd"][:2] == ["Tests first", "Red"]
    assert steps["jira-intake-triage"] == steps["incident-analysis"] == []
    # A check that a tool is NOT called is no build.
    assert build_steps({"nodes": [{"id": "a", "type": "phase", "config": {"workflow_contract": {"checks": [
        {"type": "tool_not_called", "params": {"tools": ["run_test_suite"]}}]}}}]}) == []
