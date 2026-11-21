"""DevOps workflows: protected confirmed tests, the chat test gate, watch claims, CI on the pushed commit and the sweep.

Confirmed tests are protected from the fix phase (path rule, no shell), shell calls count in chat's test gate,
the watch poller records only under the run claim, CI is judged on the pushed commit, held failure-path side
effects make the run wait, a branch is created once, test alerts move no run, structured test reports win and the
sweep claims only due runs. (The forge case itself — a weakened confirmed test fails the green gate — is in
``test_workflow_run_tdd_evidence``.)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import update

from app.models import Approval, WorkflowRun
from app.models.integration.webhook import Webhook
from app.services.approval.resolution_service import decide_pending_approval
from app.services.session.workspace import resolve_session_workspace_root
from app.services.workflow_checks.evidence import turn_evidence
from app.services.workflow_checks.test_results import parse_test_output
from app.services.workflow_checks.test_results import test_run_from_tool as run_from_tool
from app.services.workflow_runs import watch
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.path_rules import phase_path_outcomes
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.platform import ci, scm
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.services.workflow_runs.sweep import sweep_waiting_runs
from app.services.workflow_runs.test_runs import ci_state_of_head, confirm_tests, snapshot_confirmed_tests
from app.services.workflow_runs.watch_events import WatchEvent
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.test_workflow_run_failure_path import _with_policy
from tests.test_workflow_run_pause import _turn
from tests.test_workflow_run_platform_actions import FakeTools, _item, _run


def _protected_phase_definition(*, allow_shell: bool = False) -> dict:
    fix = copy.deepcopy(PHASE)
    fix["workflow_contract"]["path_rules"] = {"protect_confirmed_tests": True}
    fix["workflow_contract"]["capability_class"] = "change"
    fix["tool_policy"]["allowlist"] += ["write_workspace_file"] + (["bash"] if allow_shell else [])
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "fix", "type": "phase", "label": "Fix", "config": fix},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "fix"},
                  {"id": "2", "source_node_id": "fix", "target_node_id": "done"}],
    }


@pytest.mark.asyncio
async def test_a_fix_phase_refuses_writes_to_confirmed_tests_and_never_offers_a_shell(db):
    """Finding 1: the confirmed test file is blocked in the fix phase; bash is refused at publish and runtime."""
    errors = validate_phased_definition(_protected_phase_definition(allow_shell=True))["errors"]
    assert "path_rules_with_shell" in {error["code"] for error in errors}
    seed = json.loads(
        (Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json").read_text())
    nodes = {node["id"]: node for node in seed[0]["definition"]["nodes"]}
    assert nodes["fix"]["config"]["workflow_contract"]["path_rules"] == {"protect_confirmed_tests": True}
    assert "bash" not in nodes["fix"]["config"]["tool_policy"]["allowlist"]
    assert validate_phased_definition(seed[0]["definition"])["valid"]

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _protected_phase_definition()),
                          project_id=workspace_id,
                          session=session)
    root = Path(str(await resolve_session_workspace_root(db, session)))
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_rounding.py").write_text("def test_half_up():\n    assert True\n")
    (root / "pay").mkdir(exist_ok=True)
    (root / "pay" / "totals.py").write_text("x = 1\n")  # an existing module: the fix phase changes it
    confirm_tests(run, ["tests/test_rounding.py::test_half_up"])
    await snapshot_confirmed_tests(db, run)

    blocked = await phase_path_outcomes(db, session.id, ["tests/test_rounding.py", "pay/totals.py"])
    assert [item["evidence"]["paths"] for item in blocked] == [["tests/test_rounding.py"]]
    node = (await graph_for_run(db, run)).nodes["fix"]
    assert "bash" in phase_definition(run, node)["tool_policy"]["denylist"]


def _uses(*entries: tuple[str, dict, dict]) -> list[dict]:
    return [{"tool_name": name, "status": "success", "params": params, "result": result}
            for name, params, result in entries]


def test_shell_edits_are_changes_and_shell_test_commands_are_test_runs_in_chat():
    """Finding 2."""
    green = {"returncode": 0, "stdout": "tests/test_a.py::test_x PASSED"}
    edit = ("edit_workspace_file", {}, {})
    sed = ("bash", {"command": "sed -i s/1/2/ pay/totals.py"}, {"returncode": 0, "stdout": ""})
    pytest_via_bash = ("bash", {"command": "cd repo && pytest -q"}, green)
    suite = ("run_test_suite", {}, {"exit_code": 0, "stdout": "", "all_green": True})

    assert turn_evidence(_uses(edit, pytest_via_bash)).verification_state == "passed"
    assert turn_evidence(_uses(edit, suite, sed)).verification_state == "no_test_after_last_change"
    custom = turn_evidence(_uses(edit, ("bash", {"command": "make test"}, green)),
                           test_command_prefixes=[("make", "test")])
    assert custom.verification_state == "passed" and len(custom.test_runs) == 1


def test_a_structured_report_wins_over_printed_failure_lines():
    """Finding 9: a printed FAILED line cannot fake another test's failure."""
    printed = "FAILED tests/test_a.py::test_real - boom\nFAILED tests/test_b.py::test_fake - fake symptom\n"
    run = run_from_tool("run_test_suite", {"stdout": printed, "exit_code": 1,
                                                "failed_tests": ["tests/test_a.py::test_real"]}, source="chat")
    assert set(run["results"]) == {"tests/test_a.py::test_real"}
    junit = ('FAILED x::fake - printed\n<testsuite><testcase classname="t" name="real"><failure message="m"/>'
             '</testcase></testsuite>')
    from app.services.workflow_checks.test_output import parse

    report = parse(junit)  # the report decides: its one case, unresolved without its file; no printed line counts
    assert report.results == {} and [item["raw"] for item in report.unresolved] == ["t.real"]
    assert parse_test_output(junit) == {}


@pytest.mark.asyncio
async def test_the_poller_records_ci_only_under_the_claim_and_never_overwrites_a_concurrent_change(db, monkeypatch):
    """Findings 3 and 10: the read runs unclaimed; recording claims the current run (nothing is overwritten)."""
    definition = {"execution_kind": "phased",
                  "nodes": [{"id": "start", "type": "start"},
                            {"id": "ci", "type": "watch", "label": "CI", "config": {"conditions": ["ci.succeeded"]}},
                            {"id": "ok", "type": "outcome", "config": {"outcome": "done"}}],
                  "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "ci"},
                            {"id": "2", "source_node_id": "ci", "target_node_id": "ok", "when": "ci.succeeded"}]}
    run = await _run(db, definition, repository="github:acme/pay")
    await db.commit()

    async def read_while_a_decision_commits(db_, run_, params):
        # Meanwhile another transaction records a decision on the run and commits.
        await db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id).values(
            context={**dict(run.context or {}), "decided": "elsewhere"},
            state_version=WorkflowRun.state_version + 1).execution_options(synchronize_session=False))
        return ci.CiResult("github", ci.CI_RUNNING, reason="still running")

    monkeypatch.setattr(ci, "read_ci_status", read_while_a_decision_commits)
    assert await watch.poll_watching_runs(db) == 0
    await db.refresh(run)
    assert run.context["decided"] == "elsewhere" and run.context["ci"]["state"] == "running"

    version = run.state_version
    run.status, run.node_state = "waiting", {**run.node_state, "waiting": {"since": utc_now().isoformat()}}
    run.waiting_kind = "waiting_for_reply"
    await db.commit()
    await sweep_waiting_runs(db)  # nothing due: the run is not claimed
    await db.refresh(run)
    assert run.state_version == version  # untouched by the sweep


@pytest.mark.asyncio
async def test_ci_is_judged_on_the_pushed_commit_only(db, monkeypatch):
    """Finding 4."""
    tools = FakeTools(monkeypatch, {
        "commit_and_push_github_repository_branch": [{"status": "pushed", "head_commit": "new-sha"}],
        "list_github_action_runs": [{"workflow_runs": [
            {"name": "lint", "status": "completed", "conclusion": "success", "head_sha": "new-sha"},
            {"name": "tests", "status": "completed", "conclusion": "success", "head_sha": "old-sha"},
        ]}],
    })
    run = await _run(db, {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"}, {"id": "ok", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "ok"}]}, repository="github:acme/pay")
    run.branch = "bugfix/PAY-1-x"
    run.context = {**run.context, "local_path": "/nonexistent", "ci": {"state": "succeeded", "sha": "old-sha"}}

    assert (await scm.push(db, run, {})).ok
    assert run.context["head_sha"] == "new-sha" and "ci" not in run.context  # an earlier round's CI is gone
    # Only the lint workflow ran for the pushed commit; naming the test workflow waits for it.
    assert (await ci.read_ci_status(db, run, {})).state == "succeeded"
    assert (await ci.read_ci_status(db, run, {"workflow": "tests"})).state == "running"
    assert ci_state_of_head({"head_sha": "new-sha", "ci": {"state": "succeeded", "sha": "old-sha"}}) is None
    assert "list_github_action_runs" in tools.tools()

    target = {"repository": "github:acme/pay", "branch": "bugfix/PAY-1-x", "head_sha": "new-sha"}
    event = WatchEvent("ci.succeeded", "github", "acme/pay", branch="bugfix/PAY-1-x", sha="new-sha", workflow="lint")
    assert not watch.matches(event, target)  # one workflow's success is not the commit's
    assert watch.matches(event, {**target, "workflow": "lint"})
    assert watch.matches(WatchEvent("ci.failed", "github", "acme/pay", branch="bugfix/PAY-1-x", sha="new-sha"), target)
    assert not watch.matches(WatchEvent("ci.failed", "github", "acme/pay", branch="bugfix/PAY-1-x", sha="old-sha"),
                             target)


async def _approval(db, run) -> Approval:
    admin = await admin_user(db)
    approval = Approval(requested_by=admin.id, action="Approve tool execution", status="pending",
                        session_id=await main_session_id(db, run))
    db.add(approval)
    await db.flush()
    return approval


def _pending(approval: Approval) -> dict:
    return {"approval_required": True, "approval_id": approval.id, "approval_status": "pending"}


@pytest.mark.asyncio
async def test_a_held_round_comment_and_a_held_follow_up_make_the_run_wait_and_the_grant_goes_on(db, monkeypatch):
    """Finding 5: no orphaned approval — the run waits, the grant performs the side effect and the run goes on."""
    admin = await admin_user(db)
    tools = FakeTools(monkeypatch, {})
    item = await _item(db)
    run = await _run(db, _with_policy(max_iterations=1), work_item_id=item.id)
    session_id = await main_session_id(db, run)
    first = await _approval(db, run)
    tools.answers["add_jira_comment"] = [_pending(first), {"status": "created"}]
    await _turn(db, session_id, ["knowledge_search"])  # round 1 fails: its comment waits for the approval
    assert (run.status, run.waiting_kind, run.current_node_id) == ("waiting", "awaiting_tool_approval", "work")
    await decide_pending_approval(db, approval_id=first.id, resolved_by=admin.id, status="approved")
    assert (run.status, run.current_node_id) == ("running", "work")
    assert tools.tools() == ["add_jira_comment", "add_jira_comment"]

    second = await _approval(db, run)
    tools.answers["create_jira_ticket"] = [_pending(second), {"ticket_id": "PAY-950", "status": "created"}]
    await _turn(db, session_id, ["knowledge_search"])  # at the limit: paused, its follow-up waits
    assert (run.status, run.waiting_kind) == ("waiting", "awaiting_tool_approval")
    await decide_pending_approval(db, approval_id=second.id, resolved_by=admin.id, status="approved")
    assert (run.status, run.pause_reason, run.context["follow_up_issue"]) == ("paused", "loop_limit", "PAY-950")
    assert tools.tools().count("create_jira_ticket") == 2  # the held call and its granted rerun, one issue


@pytest.mark.asyncio
async def test_a_branch_is_created_once_when_preparing_the_working_copy_waits(db, monkeypatch):
    """Finding 7."""
    from tests.agent_definition_revision_fixtures import make_project

    project = await make_project(db)
    item = await _item(db, project_id=project.id)
    run = await _run(db, {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"}, {"id": "ok", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "ok"}]},
        work_item_id=item.id, project_id=project.id, repository="github:acme/pay")
    approval = await _approval(db, run)
    tools = FakeTools(monkeypatch, {"prepare_github_repository": [_pending(approval), {"local_path": "repos/pay"}]})
    assert (await scm.create_branch(db, run, {"branch_type": "bugfix"})).state == "approval_pending"
    assert (await scm.create_branch(db, run, {"branch_type": "bugfix"})).ok
    assert tools.tools().count("create_github_branch") == 1 and run.branch


@pytest.mark.asyncio
async def test_a_test_alert_on_a_jira_change_source_moves_no_run(db, monkeypatch):
    """Finding 8."""
    from app.services.inbound_alerts import trigger
    from tests.agent_definition_revision_fixtures import make_project

    delivered: list[dict] = []

    async def spy(db_, payload, *, project_id):
        delivered.append(payload)
        return []

    monkeypatch.setattr(watch, "deliver_jira_change", spy)
    project = await make_project(db)
    admin = await admin_user(db)
    hook = Webhook(project_id=project.id, owner_id=admin.id, name="jira", source_type="jira_change", is_active=True)
    db.add(hook)
    await db.flush()
    await trigger.receive_alert(db, webhook=hook, body=b"{}", payload={"key": "SAMPLE-1", "status": "Done"},
                                is_test=True, verified=True)
    assert delivered == []
