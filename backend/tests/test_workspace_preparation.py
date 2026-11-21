"""Environment readiness and workspace preparation.

When pytest is not installed for the device's python ('pytest' exit 127, 'python3 -m pytest' → No module named
pytest), a test-prefixed Bash must not count as ``run_test_suite``, else Tests first "passes" and the automatic
device continuations burn the red loop in a minute; the folder must not stay on main either. Here:

- a test command whose runner could not start is the environment's failure: the run pauses ``environment_not_ready``
  with the exact reason, no gate runs, no loop iteration is consumed, no continuation starts, retry re-enters the
  phase; a collection error is not a test run either (the agent's to fix) and a real run still counts;
- ``workspace.prepare`` (a node of A and B) runs the repository's declared setup in the folder when the probes fail
  and the run reaches Tests first ready; its red gate passes on a real failing test;
- foreign uncommitted changes pause the run ``workspace_dirty`` (nothing overwritten); retry after a commit goes on;
- a launcher's report (device / terminal) routes the waiting node; a dirty or unready folder pauses the run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import CodeRepository, WorkflowRun
from app.services.workflow_runs.workspace.spec import validate_environment
from tests.device_job_session_parity_support import CONFIRMED, GATEWAY, TOTALS_TEST
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _phase_turn,
    _settle,
    _workspace,
    submitted,
    systems,
)
from tests.workspace_preparation_support import SHIM, _device_at_tests_first, _server_pipeline  # noqa: F401

B_KEY = "feature-delivery-tdd"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@stub.test", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


# --- workspace.prepare on the server runtime ------------------------------------------------------------------------


async def _declare(db, project_id: str, environment: dict) -> None:
    from sqlalchemy import select

    repo = (await db.execute(select(CodeRepository).where(CodeRepository.project_id == project_id))).scalars().one()
    setup = dict(dict(repo.config_json or {}).get("coding_setup") or {})
    repo.config_json = {**dict(repo.config_json or {}), "coding_setup": {**setup, "environment": environment}}
    await db.flush()


@pytest.mark.asyncio
async def test_declared_setup_runs_in_the_folder_and_the_red_gate_passes_on_a_real_failing_test(
        client, auth_headers, db, systems):  # noqa: F811
    project, item = await _workspace(db, systems)
    environment, errors = validate_environment({
        "setup": [SHIM], "test": f"python -m pytest -rA {CONFIRMED}", "path": [".tools"],
        "check": [".tools/python -c 'import pytest'"]})
    assert errors == []
    await _declare(db, project.id, environment)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    run_id, session_id = started.json()["run"]["id"], started.json()["session_id"]
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "clarify"
    run = await db.get(WorkflowRun, run_id)
    working_copy = Path(run.context["local_path"])
    prepared = run.context["workspace_preparation"]
    assert (prepared["state"], prepared["runtime"]) == ("ready", "server")
    report = prepared["report"]
    assert report["branch"]["state"] in ("already", "checked_out") and report["branch"]["name"] == run.branch
    assert _git(working_copy, "rev-parse", "--abbrev-ref", "HEAD") == run.branch
    assert [step["exit_code"] for step in report["environment"]["setup"]] == [0]  # ran because the probe failed
    assert (working_copy / ".tools" / "python").is_file()  # in the folder, nowhere else
    assert _git(working_copy, "status", "--porcelain") == ""  # and never part of the change (local exclude)
    assert run.context["actions"]["prepare"]["result"] == "succeeded"

    # Clarify → confirmed contract → Tests first: a real failing test run with the prepared interpreter is red.
    contract = {"criteria": [{"id": "AC1", "text": "Totals round half up",
                              "tests": [f"{CONFIRMED}::test_rounds_half_up"], "command": f"pytest {CONFIRMED}"}]}
    read = {"tool_name": "read_workspace_file", "status": "success", "result": {}}
    await _phase_turn(db, session_id, [read, await submitted(db, session_id, "submit_test_contract", contract)])
    waiting = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["waiting"]
    confirmed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    assert confirmed.json()["run"]["current_node"]["id"] == "tests_first", confirmed.text
    (working_copy / CONFIRMED).write_text(TOTALS_TEST)
    done = subprocess.run([str(working_copy / ".tools" / "python"), "-m", "pytest", "-rA", "-p", "no:cacheprovider",
                           "-o", "addopts=", CONFIRMED], cwd=working_copy, capture_output=True, text=True, timeout=120)
    assert "FAILED" in done.stdout
    write = {"tool_name": "write_workspace_file", "status": "success", "result": {}}
    tests = {"tool_name": "run_test_suite", "status": "success",
             "result": {"stdout": done.stdout, "exit_code": done.returncode, "all_green": False,
                        "command": environment["test"]}}
    await _phase_turn(db, session_id, [write, tests])
    await db.refresh(run)
    assert run.gate_results["red"]["state"] == "passed", run.gate_results["red"]
    assert run.current_node_id == "implement" and run.loop_counters["loop-red"]["used"] == 0


@pytest.mark.asyncio
async def test_foreign_uncommitted_changes_pause_the_run_and_retry_goes_on_after_a_commit(
        client, auth_headers, db, systems):  # noqa: F811
    from app.services.workflow_runs.engine import restart_at

    project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    run_id = started.json()["run"]["id"]
    await _settle(client, auth_headers, run_id)
    run = await db.get(WorkflowRun, run_id)
    working_copy = Path(run.context["local_path"])
    # Someone works on main in the same folder: a tracked file changed, not committed.
    _git(working_copy, "checkout", "-q", "main")
    (working_copy / "pay" / "fees.py").write_text("def fee(amount: int) -> int:\n    return 1  # local work\n")
    await restart_at(db, run, "prepare", actor_id=None)
    await db.commit()
    await db.refresh(run)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "workspace_dirty", "action_failed")
    assert "pay/fees.py" in run.node_state["pause"]["message"]
    assert "return 1  # local work" in (working_copy / "pay" / "fees.py").read_text()  # nothing overwritten
    actions = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["actions"]
    assert {item["key"] for item in actions} >= {"retry_action", "change_plan", "abort"}
    assert next(item for item in actions if item["key"] == "retry_action")["label"] == (
        "Retry after committing or stashing the changes")
    _git(working_copy, "commit", "-qam", "local work")
    retried = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "retry_action"})
    assert retried.status_code == 200, retried.text
    await db.refresh(run)
    assert run.current_node_id == "clarify", (run.status, run.pause_reason, run.node_state)
    assert _git(working_copy, "rev-parse", "--abbrev-ref", "HEAD") == run.branch


# --- a launcher's report routes the waiting node --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_launchers_report_routes_the_waiting_preparation(client, auth_headers, db, systems):  # noqa: F811
    from app.services.workflow_runs.engine import restart_at

    run_id, working_copy, gateway, policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    # The run follows an attached octryx-claude session now: its launcher prepares its own folder.
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
    # The device's word "ready" without passing probes is not ready.
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


# --- the device cannot fetch origin; the platform hands the branch over ------------------------------------------


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
    assert body["prerequisites"] == [base]  # thin: only what the device lacks
    bundle = working_copy.parent / "branch.bundle"
    bundle.write_bytes(base64.b64decode(body["bundle"]))
    _git(device, "fetch", "-q", str(bundle), f"refs/heads/{run.branch}:refs/remotes/origin/{run.branch}")
    assert _git(device, "rev-parse", f"origin/{run.branch}") == head

    # Unknown commits: the whole branch, still usable.
    whole = (await client.post(f"{GATEWAY}/branch-bundle", headers=headers, json={"have": ["a" * 40]})).json()
    assert whole["state"] == "ready" and whole["prerequisites"] == []

    # A session that does not execute the run (never registered for it) gets nothing.
    import uuid

    other = {**headers, "X-Octryx-Session": str(uuid.uuid4())}
    refused = await client.post(f"{GATEWAY}/branch-bundle", headers=other, json={"have": []})
    assert refused.status_code != 200 and "bundle" not in refused.text


@pytest.mark.asyncio
async def test_a_branch_not_yet_in_the_platforms_copy_is_handed_over_at_its_known_commit(tmp_path):
    """The next story's branch exists only by name; the platform knows the commit it starts from (``base_sha``)."""
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
    assert _git(copy, "for-each-ref", "refs/octryx-bundle") == ""  # the helper ref is gone again
    assert (await branch_bundle(SimpleNamespace(branch="x", context={}), []))["reason"] == "run_has_no_working_copy"
