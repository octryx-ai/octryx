"""Shared harness of the phased workflow acceptance tests: Jira and GitHub stubs over local bare git remotes, the run Workspace and phase-turn helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from app.models import BuiltInToolConfig, CodeRepository, Project, Session, UserLinkedAccount
from app.models.runtime.secure_work import WorkItem, WorkItemWorkflowDefinition
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.seeding import seed_phased_workflows
from tests.fresh_interpreter_support import run_pytest_probe
from tests.phased_workflow_fixtures import admin_user, join_workspace
from tests.source_stub_support import jira_fixtures, load
from tests.test_workflow_run_tdd_evidence import phase_turn_with_history

jira_stub = load("jira_work_stub")


scm_stub = load("scm_github_stub")


JIRA_URL = "http://jira.stub.test"


GITHUB_API = "http://scm.stub.test/api/v3"


KEY = "bug-fix-reproduction"


RUN_TOOLS = ["create_jira_ticket", "add_jira_comment", "create_github_branch", "prepare_github_repository",
             "commit_and_push_github_repository_branch", "create_github_pull_request", "get_github_pull_request",
             "list_github_action_runs", "get_github_action_run_artifacts"]


BUGGY = "def round_total(value: float) -> int:\n    return int(value)\n"


REPRO_TEST = ("from pay.totals import round_total\n\n\ndef test_rounds_half_up():\n"
              "    assert round_total(2.5) == 3\n")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _remote(root: Path) -> Path:
    seed = root / "seed"
    (seed / "pay").mkdir(parents=True)
    (seed / "tests").mkdir()
    (seed / "pay" / "__init__.py").write_text("")
    (seed / "pay" / "totals.py").write_text(BUGGY)
    (seed / "pay" / "fees.py").write_text("def fee(amount: int) -> int:\n    return 0\n")  # Feature delivery (B)
    (seed / ".gitignore").write_text("__pycache__/\n*.pyc\n")  # like any repository: no bytecode in commits
    (seed / "tests" / "test_zero.py").write_text(
        "from pay.totals import round_total\n\n\ndef test_zero():\n    assert round_total(0) == 0\n")
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "-c", "user.email=t@stub.test", "-c", "user.name=t", "add", "-A")
    _git(seed, "-c", "user.email=t@stub.test", "-c", "user.name=t", "commit", "-q", "-m", "init")
    bare = root / "remotes" / "acme" / "pay.git"
    bare.parent.mkdir(parents=True)
    _git(root, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


def _transport(stub, base: str, ci_runs: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(base.split("/api/")[0])
        if request.method == "GET" and ci_runs:
            if request.url.path.endswith("/actions/runs"):
                return httpx.Response(200, json={"workflow_runs": ci_runs, "total_count": len(ci_runs)})
            if request.url.path.endswith("/artifacts"):
                return httpx.Response(200, json={"artifacts": [], "total_count": 0})
        status, payload = stub.handle(request.method, request.url.raw_path.decode(),
                                      request.headers.get("Authorization"), request.content)
        return httpx.Response(status, content=payload) if isinstance(payload, bytes) else httpx.Response(
            status, json=payload)

    return httpx.MockTransport(handler)


@pytest.fixture
def systems(tmp_path, monkeypatch):
    """The stubbed Jira and GitHub behind the connectors' egress, and the run's workspace under tmp."""
    import app.services.session.workspace as workspace
    import app.tools.connectors.common as connectors
    import app.tools.jira_impl._jira_query_ticket_actions as jira_comments
    import app.tools.jira_impl._jira_ticket_tools as jira_tickets

    bare = _remote(tmp_path)
    jira_stub.reset()
    scm_stub.configure(tmp_path / "remotes")
    ci_runs = []
    transports = {"jira": _transport(jira_stub, JIRA_URL), "github": _transport(scm_stub, GITHUB_API, ci_runs)}

    def egress(connection):
        return transports[str(connection)]

    for module in (connectors, jira_comments, jira_tickets):
        monkeypatch.setattr(module, "egress_transport", egress)

    async def base_dir(_db):
        return tmp_path / "sessions"

    monkeypatch.setattr(workspace, "get_session_workspace_base_dir", base_dir)
    return {"bare": bare, "remotes": tmp_path / "remotes", "ci_runs": ci_runs}


async def _workspace(db, systems) -> tuple[Project, WorkItem]:
    admin = await admin_user(db)
    project = Project(name=f"payments-{bare_suffix(systems)}", is_active=True, config={
        # The Workspace's own rule: its write tools are explicitly allowed.
        "tool_policy": {"allowlist": RUN_TOOLS},
    })
    db.add(project)
    await db.flush()
    await join_workspace(db, admin, project.id)  # the requester of the runs, a member like a real one
    # The Workspace's own Jira and GitHub connections (tool configs), pointing at the stubs.
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, is_active=True, config={
        "jira_url": JIRA_URL, "jira_auth_mode": "basic", "jira_username": jira_fixtures.STUB_USERNAME,
        "jira_password": jira_fixtures.STUB_TOKEN}))
    db.add(BuiltInToolConfig(tool_name="github", project_id=project.id, is_active=True, config={
        "github_url": GITHUB_API, "github_clone_base_url": f"file://{systems['remotes']}",
        "github_allowed_repositories": ["acme/pay"], "github_token": "stub-token"}))
    await db.flush()
    db.add(CodeRepository(project_id=project.id, provider="github", name="acme/pay", repo_root="/srv/pay",
                          config_json={"operation_policy": {"branch": True, "write": True, "pr": True},
                                       "coding_setup": {"owners": ["pay-lead"]}}))
    db.add(UserLinkedAccount(user_id=admin.id, platform="github", username="requester-gh"))
    db.add(WorkItemWorkflowDefinition(
        name="Bug fix states", states_json=[], is_default=True, is_active=True, created_by=admin.id,
        updated_by=admin.id, project_id=project.id,
        mappings_json={"review": {"sync_back": False}, "done": {"sync_back": False},
                       "blocked": {"sync_back": False}}))
    item = WorkItem(source_type="manual", source_instance="octryx", source_key=f"OCX-{bare_suffix(systems)}",
                    source_project_key="PAY", title="Totals round down instead of half up",
                    description=("Steps: add 2.5 to the cart\nExpected: 3\nActual: 2.5 becomes 2\n"
                                 "Environment: the pay service, main"), project_id=project.id, work_state="intake",
                    labels_json=["full-flow"])  # these tests walk every gate (the bug seed's size class L)
    db.add(item)
    await db.flush()
    await seed_phased_workflows(db, admin_user=admin)
    return project, item


def bare_suffix(systems) -> str:
    return str(abs(hash(str(systems["bare"]))) % 100000)


async def _settle(client, headers, run_id: str) -> dict:
    """Allow every step that waits for a tool approval in the run card (the requester's consent)."""
    for _ in range(10):
        run = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=headers)).json()["run"]
        if run["waiting_kind"] != "awaiting_tool_approval":
            return run
        allowed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=headers,
                                    json={"action": "approve_tool"})
        assert allowed.status_code == 200, allowed.text
    raise AssertionError("tool approvals did not settle")


def _pytest(working_copy: Path) -> dict:
    """A real test run in the run's working copy, as run_test_suite reports it."""
    done = run_pytest_probe(working_copy, "tests")
    return {"tool_name": "run_test_suite", "status": "success",
            "result": {"stdout": done.stdout, "exit_code": done.returncode, "all_green": done.returncode == 0}}


async def submitted(db, session_id: str, tool: str, arguments: dict) -> dict:
    """The phase's output submitted as the chat tool records it: the run's record and the turn's tool call."""
    from app.services.workflow_runs.phase_outputs import submit_output
    from app.services.workflow_runs.records import active_run_for_session

    answer = await submit_output(db, await active_run_for_session(db, session_id), tool, arguments)
    assert answer["state"] == "recorded", answer
    return {"tool_name": tool, "status": "success", "result": {"status": "recorded"}}


REPRODUCTION = {"tests": ["tests/test_totals.py::test_rounds_half_up"], "symptom": "assert 2 == 3"}


async def _phase_turn(db, session_id: str, history: list[dict]) -> None:
    session = await db.get(Session, session_id)
    resolution = await run_turn_resolution(db, session, user_message="Work on this phase.")
    assert resolution["status"] == "matched", resolution
    await phase_turn_with_history(db, session_id, resolution, history)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
