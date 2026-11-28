"""Environment readiness and workspace preparation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import WorkflowRun
from tests.device_job_session_parity_support import GATEWAY
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _phase_turn,
    _settle,
    _workspace,
    submitted,
    systems,
)
from tests.workspace_preparation_support import SHIM, _device_at_tests_first, _server_pipeline  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")

B_KEY = "feature-delivery-tdd"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@stub.test", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.asyncio
async def test_a_launchers_report_routes_the_waiting_preparation(client, auth_headers, db, systems):  # noqa: F811
    from app.services.workflow_runs.engine import restart_at

    run_id, working_copy, gateway, policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    await restart_at(db, run, "prepare", actor_id=None)
    await db.commit()
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "prepare")
    prep = run.context["workspace_preparation"]
    assert (prep["state"], prep["runtime"]) == ("pending", "terminal")
    from app.services.workflow_runs.octryx.contract import run_contract

    contract = await run_contract(db, run)
    assert contract["preparation"]["state"] == "pending" and contract["preparation"]["branch"] == run.branch

    def report(branch: dict, environment: dict | None = None) -> dict:
        return {"node_id": "prepare", "entry": run.node_state["entry"], "root": str(working_copy), "runtime": "device",
                "branch": branch, **({"environment": environment} if environment else {})}

    dirty = await client.post(f"{GATEWAY}/workspace-preparation", headers=headers, json=report(
        {"state": "dirty", "name": run.branch, "current": "main", "dirty_files": ["pay/fees.py"],
         "detail": "the folder is on 'main' with uncommitted changes to 1 tracked file(s)"}))
    assert dirty.status_code == 200, dirty.text
    assert dirty.json()["state"] == "not_ready" and dirty.json()["workflow_run"]["paused"]["reason"] == "workspace_dirty"
    retried = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "retry_action"})
    assert retried.status_code == 200, retried.text
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "prepare")
    ready = await client.post(f"{GATEWAY}/workspace-preparation", headers=headers, json=report(
        {"state": "checked_out", "name": run.branch, "previous": "main"},
        {"state": "ready", "probes": [{"what": "test: python -m pytest", "ok": True}], "setup": []}))
    assert ready.json()["state"] == "ready", ready.text
    await db.refresh(run)
    assert run.current_node_id == "clarify" and run.context["actions"]["prepare"]["result"] == "succeeded"
    from app.services.workflow_runs.workspace.preparation import decide

    assert not decide({"branch": {"state": "already"}, "environment": {"state": "ready", "probes": [
        {"what": "lint: flake8", "ok": False}]}}).ok


def test_the_declared_paths_and_the_test_report_are_excluded_from_the_change():
    from app.services.workflow_runs.workspace.spec import local_excludes, runtime_environment

    declared = {"source": "declared", "test": "python -m pytest -v tests/ --junitxml=test-reports/report.xml",
                "path": [".venv/bin"], "setup": []}
    assert local_excludes(declared) == ["/.venv/", "/test-reports/"]
    assert runtime_environment(declared)["exclude"] == ["/.venv/", "/test-reports/"]
    assert local_excludes({"test": "pytest --junit-xml report.xml", "path": []}) == ["/report.xml"]
    assert local_excludes({"test": "pytest --junitxml=/tmp/r.xml --junitxml=../r.xml", "path": ["/usr/bin"]}) == []


@pytest.mark.asyncio
async def test_the_device_gets_the_runs_branch_as_a_bundle_only_for_its_own_run(client, auth_headers, db,
                                                                                 systems):  # noqa: F811
    import base64

    run_id, working_copy, _gateway, _policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    base = _git(working_copy, "rev-parse", "HEAD")
    _git(working_copy, "checkout", "-q", "-B", run.branch)
    (working_copy / "story.py").write_text("# the previous story, pushed from the platform's copy\n")
    _git(working_copy, "add", "story.py")
    _git(working_copy, "commit", "-q", "-m", "previous story")
    head = _git(working_copy, "rev-parse", "HEAD")
    device = working_copy.parent / "device"
    _git(working_copy.parent, "clone", "-q", "--no-local", str(working_copy), str(device))
    _git(device, "checkout", "-q", "--detach", base)
    for ref in _git(device, "for-each-ref", "--format=%(refname)", "refs/remotes", "refs/heads").splitlines():
        _git(device, "update-ref", "-d", ref)
    _git(device, "reflog", "expire", "--expire=now", "--all")
    _git(device, "gc", "-q", "--prune=now")
    assert subprocess.run(["git", "cat-file", "-e", head], cwd=device).returncode != 0

    answer = await client.post(f"{GATEWAY}/branch-bundle", headers=headers, json={"have": [base, "not-a-sha"]})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["state"], body["ref"], body["head"]) == ("ready", f"refs/heads/{run.branch}", head)
    assert body["prerequisites"] == [base]
    bundle = working_copy.parent / "branch.bundle"
    bundle.write_bytes(base64.b64decode(body["bundle"]))
    _git(device, "fetch", "-q", str(bundle), f"refs/heads/{run.branch}:refs/remotes/origin/{run.branch}")
    assert _git(device, "rev-parse", f"origin/{run.branch}") == head

    whole = (await client.post(f"{GATEWAY}/branch-bundle", headers=headers, json={"have": ["a" * 40]})).json()
    assert whole["state"] == "ready" and whole["prerequisites"] == []

    import uuid

    other = {**headers, "X-Octryx-Session": str(uuid.uuid4())}
    refused = await client.post(f"{GATEWAY}/branch-bundle", headers=other, json={"have": []})
    assert refused.status_code != 200 and "bundle" not in refused.text


@pytest.mark.asyncio
async def test_a_branch_not_yet_in_the_platforms_copy_is_handed_over_at_its_known_commit(tmp_path):
    from types import SimpleNamespace

    from app.services.workflow_runs.workspace.branch_bundle import branch_bundle

    copy = tmp_path / "copy"
    copy.mkdir()
    _git(copy, "init", "-q", "-b", "main")
    (copy / "a.py").write_text("a = 1\n")
    _git(copy, "add", "-A")
    _git(copy, "commit", "-q", "-m", "story 1")
    base = _git(copy, "rev-parse", "HEAD")
    run = SimpleNamespace(branch="feature/OCX-22-s3", context={"local_path": str(copy), "base_sha": base})
    body = await branch_bundle(run, [])
    assert body["state"] == "ready" and body["head"] == base and body["ref"].startswith("refs/octryx-bundle/")
    assert _git(copy, "for-each-ref", "refs/octryx-bundle") == ""
    assert (await branch_bundle(SimpleNamespace(branch="x", context={}), []))["reason"] == "run_has_no_working_copy"
