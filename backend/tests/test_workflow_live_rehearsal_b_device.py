"""Feature delivery (B) on a device, end to end, without external services.

The scenario covers, with the real pieces:

- a device job session through the real gateway endpoints (``register``, ``repository``, ``tool-check``,
  ``tool-executed``, ``verification``) with a real device grant; the launcher's own code (``octryx_claude``) builds
  the hook payloads: the run contract it remembers, the working copy facts, the JUnit report it attaches;
- a repository with a declared environment (setup that makes the folder's interpreter, the declared test command
  *with* ``--junitxml`` and a lint command), ``workspace.prepare`` on the server and the launcher's preparation report;
- Clarify on the device: a recorded read, the test contract submitted over MCP with roles (new / regression); the
  server drafts the plan; the requester confirms it (the roles shown);
- Tests first: the declared command runs verbatim (and the lint command), new tests red and the regression test green
  **from the JUnit report**, keyed by the canonical test id; Implement: green, the confirmed test protected;
- the independent review gate, the read-only documentation draft on the device (the reviewed tree proven unchanged
  before the push), the push to a local bare remote, the PR on the GitHub stub, CI on the pushed commit
  whose pipeline uploads its JUnit report as an artifact — the CI test run keyed by the same canonical ids.

No loop iteration is consumed and nothing pauses on the way: every gate decides on evidence the platform could key.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import CodeRepository
from app.services.workflow_runs.documentation import s1_graph
from app.services.workflow_runs.review.runner import run_due_reviews
from app.services.workflow_runs.watch import poll_watching_runs
from app.services.workflow_runs.workspace.spec import validate_environment
from tests.device_job_session_parity_support import B_KEY, GATEWAY, REMOTE, _binding, _device, _headers, _register
from tests.documentation_acceptance_support import DOCUMENTATION
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _settle,
    _workspace,
    scm_stub,
    systems,
)
from tests.workflow_live_rehearsal_b_device_support import (
    Device,
    _last_test_run,
    _outcomes,
    _pipeline_junit,
    _run,
)
from tests.workflow_run_review_support import ScriptedReviewer
from tests.workspace_preparation_support import SHIM

DECLARED_TEST = "python -m pytest -v tests/ --junitxml=test-reports/report.xml"
DECLARED_LINT = "python -m ruff check --no-cache --isolated --select F pay tests"
NEW = ["tests/test_fees.py::test_fee_is_two_percent", "tests/test_fees.py::test_fee_rounds_down"]
REGRESSION = ["tests/test_zero.py::test_zero"]
FEES_TEST = ("from pay.fees import fee\n\n\ndef test_fee_is_two_percent():\n    assert fee(100) == 2\n\n\n"
             "def test_fee_rounds_down():\n    assert fee(149) == 2\n")
FEES = "def fee(amount: int) -> int:\n    return amount * 2 // 100\n"

async def _switch_off_python_style(db, project):
    # The rehearsal's working copy has no ruff: the Workspace switches the Python formatter and linter off (the
    # admin's per-language switch, code style step iv); a missing tool is otherwise red by design.
    from app.services.code_style.store import set_workspace_profile

    await set_workspace_profile(db, project, {"languages": {"python": {
        "formatter": {"enabled": False}, "linter": {"enabled": False}}}}, actor_id=(await admin_user(db)).id)


async def _declare_environment(db, project):
    environment, errors = validate_environment({
        "setup": [SHIM], "test": DECLARED_TEST, "lint": DECLARED_LINT, "path": [".tools"],
        "check": [".tools/python -c 'import pytest, ruff'"]})
    assert errors == []
    repo = (await db.execute(CodeRepository.__table__.select().where(
        CodeRepository.project_id == project.id))).first()
    stored = await db.get(CodeRepository, repo.id)
    setup = dict(dict(stored.config_json or {}).get("coding_setup") or {})
    stored.config_json = {**dict(stored.config_json or {}), "coding_setup": {**setup, "environment": environment}}
    policy = dict(project.config["tool_policy"])
    project.config = {**project.config, "tool_policy": {
        **policy, "allowlist": [*policy["allowlist"], "list_github_action_runs", "get_test_results"]}}
    await db.commit()


async def _start_and_prepare_on_server(client, auth_headers, db, item):
    # --- start: ticket, branch, workspace.prepare (the declared setup runs in the folder) -------------------------
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    run_id = started.json()["run"]["id"]
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "clarify"
    run = await _run(db, run_id)
    working_copy = Path(run.context["local_path"])
    assert run.context["workspace_preparation"]["state"] == "ready"
    assert (working_copy / ".tools" / "python").is_file()
    return run_id


async def _bind_device_session(client, db, project, run_id, bare, tmp_path):
    # --- the device job session: its own clone (origin: the hosted repository, not fetchable from here), registered
    # with the run, the job folder bound as the run's repository ------------------------------------------------------
    folder = tmp_path / "device" / "pay"
    folder.parent.mkdir()
    subprocess.run(["git", "clone", "-q", str(bare), str(folder)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "set-url", "origin", REMOTE], cwd=folder, check=True)
    token = await _device(db, await admin_user(db), [str(folder.parent)])
    headers = _headers(token, project.id, run_id)
    assert (await _register(client, headers))["status"] == 200
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True, text=True).stdout.strip()
    bound = await client.post(f"{GATEWAY}/repository", headers=headers,
                              json={**_binding(str(folder)), "head_commit": head})
    assert bound.status_code == 200, bound.text
    device = Device(client, db, headers, folder, tmp_path / "octryx", run_id)
    return device, folder, headers


async def _prepare_on_device(client, db, run_id, device, folder, headers):
    # The run follows the device session now: its launcher prepares the job folder (workspace.prepare on the device).
    from octryx_claude import workspace_prep as launcher_prep  # the support module put the launcher on sys.path

    from app.services.workflow_runs.engine import restart_at

    await restart_at(db, await _run(db, run_id), "prepare", actor_id=None)
    await db.commit()
    contract = await device.contract()
    assert contract["preparation"]["state"] == "pending"
    assert contract["preparation"]["environment"]["test"] == DECLARED_TEST  # what the launcher runs verbatim
    assert contract["preparation"]["environment"]["exclude"] == ["/.tools/", "/test-reports/"]
    report = launcher_prep.prepare(contract, folder, runtime="device")
    assert report.get("environment", {}).get("state") == "ready", (report["branch"], report["remote_url"])
    prepared = await client.post(f"{GATEWAY}/workspace-preparation", headers=headers, json=report)
    assert prepared.status_code == 200 and prepared.json()["state"] == "ready", prepared.text
    assert (await _run(db, run_id)).current_node_id == "clarify"
    assert report["branch"]["state"] == "checked_out" and (folder / ".tools" / "python").is_file()  # setup ran
    excluded = (folder / ".git" / "info" / "exclude").read_text().splitlines()
    assert {"/.tools/", "/test-reports/"} <= set(excluded)  # neither the interpreter nor a report enters the change


async def _clarify_on_device(client, auth_headers, db, run_id, device):
    # --- Clarify: read, then the contract as data with each test's role ---------------------------------------------
    await device.read("pay/fees.py")
    submitted = await device.mcp("submit_test_contract", {"summary": "Fees are two percent", "criteria": [
        {"id": "AC1", "text": "The fee is two percent, rounded down", "command": DECLARED_TEST,
         "tests": [{"id": test_id, "role": "new"} for test_id in NEW]},
        {"id": "AC2", "text": "Totals of zero stay zero", "command": DECLARED_TEST,
         "tests": [{"id": test_id, "role": "regression"} for test_id in REGRESSION]}]})
    assert submitted["state"] == "recorded", submitted
    clarified = await device.stop()
    assert clarified["state"] == "passed", clarified
    view = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]
    assert view["current_node"]["id"] == "contract"
    assert view["waiting"]["payload"]["test_roles"] == {**dict.fromkeys(NEW, "new"),
                                                        **dict.fromkeys(REGRESSION, "regression")}
    confirmed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert confirmed.json()["run"]["current_node"]["id"] == "tests_first", confirmed.text
    run = await _run(db, run_id)
    assert run.context["confirmed_tests"] == NEW + REGRESSION


async def _tests_first_red_by_role(db, run_id, device):
    # --- Tests first: the tests written, the declared command and lint verbatim, red by role from the JUnit report ---
    assert (await device.write("tests/test_fees.py", FEES_TEST))["decision"] == "allow"
    red = await device.bash(DECLARED_TEST)
    assert red.returncode == 1 and "2 failed, 1 passed" in red.stdout
    assert (await device.bash(DECLARED_LINT)).returncode == 0
    answer = await device.stop()
    assert answer["state"] == "passed", answer.get("detail")
    run = await _run(db, run_id)
    assert run.gate_results["red"]["state"] == "passed", run.gate_results["red"]
    recorded = _last_test_run(run)
    assert recorded["source"] == "octryx" and recorded["files"] == ["tests/test_fees.py", "tests/test_zero.py"]
    assert _outcomes(recorded) == {**dict.fromkeys(NEW, "failed"), **dict.fromkeys(REGRESSION, "passed")}
    assert "unresolved" not in recorded and run.context["tests"]["red_seen"] is True
    assert run.current_node_id == "implement" and run.loop_counters["loop-red"]["used"] == 0


async def _implement_green(db, run_id, device):
    # --- Implement: the confirmed test protected, the code changed, green ---------------------------------------------
    protected = await device.write("tests/test_fees.py", FEES_TEST.replace("== 2", "== 0"), tool="Edit")
    assert (protected["decision"], protected["reason"]) == ("deny", "confirmed_test_protected")
    assert (await device.write("pay/fees.py", FEES, tool="Edit"))["decision"] == "allow"
    green = await device.bash(DECLARED_TEST)
    assert green.returncode == 0, green.stdout
    assert (await device.bash(DECLARED_LINT)).returncode == 0
    answer = await device.stop()
    assert answer["state"] == "passed", answer.get("detail")
    run = await _run(db, run_id)
    assert run.gate_results["green"]["state"] == "passed", run.gate_results["green"]
    assert set(_outcomes(_last_test_run(run)).values()) == {"passed"} and len(_last_test_run(run)["results"]) == 3


async def _review_draft_push_and_ci(client, auth_headers, db, run_id, device, bare, tmp_path):
    # --- review gate → documentation draft (read-only) → reviewed tree unchanged → push → PR → CI --------------------
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(
        {"verdict": "pass", "summary": "The fee is minimal and tested.", "findings": []}).factory) == 1
    view = await _settle(client, auth_headers, run_id)
    assert view["current_node"]["id"] == "doc_draft", view
    run = await _run(db, run_id)
    assert run.gate_results["review"]["state"] == "passed", run.gate_results["review"]
    drafted = await device.mcp("submit_feature_documentation", DOCUMENTATION)
    assert drafted["state"] == "recorded", drafted
    answer = await device.stop()
    assert answer["state"] == "passed", answer.get("detail")
    view = await _settle(client, auth_headers, run_id)
    assert view["current_node"]["id"] == "ci", view
    run = await _run(db, run_id)
    assert s1_graph.facts(run)["tree_check"]["tree"] == run.context["review"]["tree"]  # the draft changed nothing
    head = run.context["head_sha"]
    assert subprocess.run(["git", "cat-file", "-e", head], cwd=bare).returncode == 0  # pushed
    pushed = subprocess.run(["git", "diff", "--name-only", f"main..{head}"], cwd=bare, capture_output=True,
                            text=True).stdout.split()
    assert sorted(pushed) == ["pay/fees.py", "tests/test_fees.py"]  # the change only: no report, no interpreter
    assert scm_stub.PULLS["acme/pay#1"]["head"]["ref"] == run.branch

    junit = _pipeline_junit(bare, head, tmp_path)
    scm_stub.report_run("acme", "pay", name="tests", head_sha=head, conclusion="success",
                        artifacts={"test-reports": {"report.xml": junit}})
    assert await poll_watching_runs(db) == 1
    run = await _run(db, run_id)
    assert run.current_node_id == "merged" and run.context["ci"]["state"] == "succeeded"
    ci_run = _last_test_run(run)
    assert ci_run["source"] == "ci" and ci_run["sha"] == head
    assert _outcomes(ci_run) == dict.fromkeys(NEW + REGRESSION, "passed")  # the same canonical ids as the device
    assert "unresolved" not in ci_run


@pytest.mark.asyncio
async def test_feature_delivery_on_a_device_from_clarify_to_ci_with_canonical_test_evidence(
        client, auth_headers, db, systems, tmp_path):  # noqa: F811 - the imported fixture
    project, item = await _workspace(db, systems)
    await _switch_off_python_style(db, project)
    await _declare_environment(db, project)
    run_id = await _start_and_prepare_on_server(client, auth_headers, db, item)
    device, folder, headers = await _bind_device_session(client, db, project, run_id, systems["bare"], tmp_path)
    await _prepare_on_device(client, db, run_id, device, folder, headers)
    await _clarify_on_device(client, auth_headers, db, run_id, device)
    await _tests_first_red_by_role(db, run_id, device)
    await _implement_green(db, run_id, device)
    await _review_draft_push_and_ci(client, auth_headers, db, run_id, device, systems["bare"], tmp_path)

    # --- the merge is observed by the same poll (no webhook): an open PR stays watched, a merged one is seen -------
    assert await poll_watching_runs(db) == 0
    scm_stub.merge("acme", "pay", 1)
    assert await poll_watching_runs(db) == 1
    run = await _run(db, run_id)
    met = run.context["watched"]["merged"]
    assert (met["condition"], met["source"]) == ("pr.merged", "poll") and run.current_node_id == "doc_final"

    # Nothing looped, nothing paused on the platform's evidence.
    assert all(int(counter.get("used") or 0) == 0 for counter in dict(run.loop_counters or {}).values())
    assert "evidence_unresolved" not in run.context


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
