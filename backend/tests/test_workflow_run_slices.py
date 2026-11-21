"""DevOps workflows S6: sub-agent work packages of a phase.

A phase that declares ``sub_agents`` delegates slices to a named agent: one worktree branch and one child per
slice, the phase's contract on the child (incl. the protected confirmed tests), run-budgeted time, at most
``max_parallel`` at once and ``iterations`` per slice; a child's turn records a structured slice result (never the
phase's); a merge conflict fails the phase's gate and loops back with findings; re-delegation reuses the worktree.
octryx-claude: SubagentStop reports per child.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from app.models import Session, ToolCall, WorkflowRunSession
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.path_rules import phase_path_outcomes
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.slices import delegate as delegate_module
from app.services.workflow_runs.slices.delegate import delegate_slices
from app.services.workflow_runs.slices.results import merge_slices
from app.services.workflow_runs.test_runs import confirm_tests, snapshot_confirmed_tests
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.test_workflow_run_tdd_evidence import phase_turn_with_history


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@test", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _definition() -> dict:
    implement = copy.deepcopy(PHASE)
    implement["workflow_contract"].update(capability_class="change",
                                          path_rules={"protect_confirmed_tests": True, "create": ["**"]},
                                          checks=[{"type": "tool_called", "params": {"tools": ["run_test_suite"]},
                                                   "blocking": True, "description": "The tests ran"}])
    implement["tool_policy"]["allowlist"] = ["read_workspace_file", "edit_workspace_file", "run_test_suite",
                                             "delegate_slices", "merge_slices"]
    implement["sub_agents"] = {"max_parallel": 2, "iterations": 2}  # children run as the phase agent
    return {
        "execution_kind": "phased",
        "budget": {"active_seconds": 5400},
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "implement", "type": "phase", "label": "Implement", "config": implement},
                  {"id": "merged", "type": "gate", "config": {"phase": "implement", "checks": [
                      {"type": "slices_merged", "params": {}, "blocking": True, "description": "Slices merged"}]}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "implement"},
                  {"id": "2", "source_node_id": "implement", "target_node_id": "merged"},
                  {"id": "3", "source_node_id": "merged", "target_node_id": "done", "when": "passed"},
                  {"id": "loop", "source_node_id": "merged", "target_node_id": "implement", "when": "failed",
                   "kind": "loop", "max_iterations": 2, "label": "Slices ↔ merge"}],
    }


class Launcher:
    def __init__(self):
        self.calls = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def launcher(monkeypatch):
    fake = Launcher()
    monkeypatch.setattr(delegate_module, "launch_children", fake)
    return fake


async def _run_with_repo(db, tmp_path: Path):
    admin = await admin_user(db)
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pay.py").write_text("def total(x):\n    return x\n")
    (repo / "tests" / "test_pay.py").write_text("def test_total():\n    assert True\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition()),
                          project_id=workspace_id, session=session)
    run.branch = "feature/PAY-1-totals"
    run.context = {**run.context, "local_path": str(repo)}
    confirm_tests(run, ["tests/test_pay.py::test_total"])
    await snapshot_confirmed_tests(db, run)
    await db.flush()
    return run, session, repo


def _suite(green: bool = True) -> list[dict]:
    return [{"tool_name": "edit_workspace_file", "status": "success", "params": {}, "result": {}},
            {"tool_name": "run_test_suite", "status": "success", "params": {},
             "result": {"exit_code": 0 if green else 1, "stdout": "tests/test_pay.py::test_total PASSED",
                        "all_green": green}}]


async def _child_turn(db, child_id: str) -> None:
    child = await db.get(Session, child_id)
    resolution = await run_turn_resolution(db, child, user_message="Work on the slice.")
    assert resolution["workflow_run"]["slice"] == dict(child.metadata_)["workflow_run_slice"]["key"]
    await phase_turn_with_history(db, child_id, resolution, _suite())


def test_a_phase_declares_its_sub_agents_within_the_limits():
    assert validate_phased_definition(_definition())["valid"]
    too_many = _definition()
    too_many["nodes"][1]["config"]["sub_agents"]["max_parallel"] = 6
    assert "invalid_sub_agents" in {error["code"] for error in validate_phased_definition(too_many)["errors"]}


@pytest.mark.asyncio
async def test_slices_run_in_own_worktrees_under_the_phase_contract_and_report_structured_results(
        db, tmp_path, launcher):
    run, session, repo = await _run_with_repo(db, tmp_path)
    delegated = await delegate_slices(db, parent_session=session, slices=[
        {"key": "s1", "title": "Totals", "task": "Round totals.", "tests": ["tests/test_pay.py::test_total"]},
        {"key": "s2", "title": "Edge", "task": "Edge cases."}])
    assert [item["status"] for item in delegated["slices"]] == ["running", "running"]
    assert len(launcher.calls[0]["children"]) == 2 and launcher.calls[0]["seconds"] == 5400  # run budget, not 300
    slices = run.context["slices"]
    worktree = Path(slices["s1"]["path"])
    assert _git(worktree, "rev-parse", "--abbrev-ref", "HEAD") == "feature/PAY-1-totals--s1"
    child_id = slices["s1"]["child_session_id"]
    binding = (await db.get(Session, child_id)).metadata_
    assert binding["workspace_root"] == str(worktree)
    roles = {row.role for row in (await db.execute(
        WorkflowRunSession.__table__.select().where(WorkflowRunSession.run_id == run.id))).all()}
    assert "child" in roles
    # The child works under the phase's contract: the confirmed test is protected in its own worktree too.
    blocked = await phase_path_outcomes(db, child_id, ["tests/test_pay.py", "pay.py"])
    assert [item["evidence"]["paths"] for item in blocked] == [["tests/test_pay.py"]]
    # Review fixes: the child inherits exactly the run's protected paths — by any spelling, through a symlink, the
    # test runner's configuration and git's own files.
    (worktree / "link.py").symlink_to(worktree / "tests" / "test_pay.py")
    for path in ("TESTS/Test_Pay.py", "link.py", "conftest.py", "tests/conftest.py", "pyproject.toml", ".git",
                 ".gitattributes", ".pytest.ini", "pytest.toml", "tests/__init__.py", "sitecustomize.py",
                 "evilplug.py"):
        assert await phase_path_outcomes(db, child_id, [path]), path
    assert await phase_path_outcomes(db, child_id, ["pay.py"]) == []  # an existing module: the slice's work
    # Packaging metadata, bytecode and a new package named like an installed distribution (the server checks the
    # working copy's environment and the standard library).
    (worktree / ".venv" / "lib" / "python3.12" / "site-packages" / "iniconfig").mkdir(parents=True)
    for path in ("pay.egg-info/entry_points.txt", "evil-1.0.dist-info/METADATA", "__pycache__/pay.cpython-312.pyc",
                 "x.pth", "iniconfig/__init__.py", "json/__init__.py"):
        assert await phase_path_outcomes(db, child_id, [path]), path
    (worktree / "link.py").unlink()

    (worktree / "pay.py").write_text("def total(x):\n    return round(x)\n")
    await _child_turn(db, child_id)
    s1 = run.context["slices"]["s1"]
    assert (s1["status"], s1["result"]["files"]) == ("completed", ["pay.py"])
    assert s1["result"]["tests"]["passed"] == ["tests/test_pay.py::test_total"] and s1["result"]["commit"]
    assert run.current_node_id == "implement" and "implement" not in run.gate_results  # the phase did not advance


@pytest.mark.asyncio
async def test_a_merge_conflict_loops_back_and_the_slice_is_re_delegated_within_its_iterations(db, tmp_path, launcher):
    from app.services.workflow_runs.records import WorkflowRunError

    run, session, repo = await _run_with_repo(db, tmp_path)
    await delegate_slices(db, parent_session=session, slices=[{"key": "s1", "task": "a"}, {"key": "s2", "task": "b"}])
    with pytest.raises(WorkflowRunError) as limit:
        await delegate_slices(db, parent_session=session, slices=[{"key": "s3", "task": "c"}])
    assert limit.value.code == "parallel_limit"
    for key, body in (("s1", "return x + 1"), ("s2", "return x + 2")):  # both change the same line
        path = Path(run.context["slices"][key]["path"])
        (path / "pay.py").write_text(f"def total(x):\n    {body}\n")
        await _child_turn(db, run.context["slices"][key]["child_session_id"])
    merged = await merge_slices(db, parent_session=session)
    statuses = {item["key"]: item["status"] for item in merged["slices"]}
    assert statuses == {"s1": "merged", "s2": "conflict"} and "x + 1" in (repo / "pay.py").read_text()
    assert _git(repo, "status", "--porcelain") == ""  # the conflict was aborted, never half-merged

    resolution = await run_turn_resolution(db, session, user_message="Merge done.")
    await phase_turn_with_history(db, session.id, resolution, _suite())
    assert run.gate_results["merged"]["state"] == "failed" and run.current_node_id == "implement"
    findings = phase_definition(run, type("N", (), {"config": _definition()["nodes"][1]["config"],
                                                    "title": "Implement", "id": "implement"})())
    assert any("slice s2 (conflict" in line for line in findings["workflow_contract"]["workflow_run_phase"]["slices"])

    old_child = run.context["slices"]["s2"]["child_session_id"]
    again = await delegate_slices(db, parent_session=session, slices=[
        {"key": "s2", "findings": ["Conflicts with s1 in pay.py: build on the merged total."]}])
    s2 = run.context["slices"]["s2"]
    assert s2["iteration"] == 2 and s2["child_session_id"] != old_child and again["status"] == "delegated"
    assert "x + 1" in (Path(s2["path"]) / "pay.py").read_text()  # reset to the merged state
    assert "build on the merged total" in launcher.calls[-1]["children"][0]["task"]
    await phase_turn_with_history(db, old_child, await run_turn_resolution(
        db, await db.get(Session, old_child), user_message="late"), _suite())
    assert run.context["slices"]["s2"]["status"] == "running"  # an older child's report changes nothing
    s2_path = Path(s2["path"])
    (s2_path / "pay.py").write_text("def total(x):\n    return x + 3\n")
    await _child_turn(db, s2["child_session_id"])
    run.context["slices"]["s2"]["status"] = "failed"
    run.context = dict(run.context)
    refused = await delegate_slices(db, parent_session=session, slices=[{"key": "s2", "findings": ["once more"]}])
    assert refused["refused"] == [{"key": "s2", "reason": "slice_iteration_limit"}]


@pytest.mark.asyncio
async def test_octryx_subagent_stop_reports_per_child_and_never_advances(db):
    from tests.workflow_run_octryx_support import _bound_run, _call

    run, gateway, _key, _workspace = await _bound_run(db)
    hook = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_child_1",
            "agent_id": "agent-7"}
    await record_tool_execution(db, session=gateway, hook_input=hook)
    row = (await db.execute(ToolCall.__table__.select().where(ToolCall.request_id == "toolu_child_1"))).first()
    assert row.parameters["agent_id"] == "agent-7"

    from app.services.workflow_runs.octryx.stop import run_stop

    at = utc_now()
    rows = [_call(gateway, "Bash", at=at, command="pytest -q", excerpt="", agent_id="agent-7")]
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "SubagentStop", "agent_id": "agent-7"},
                            tool_calls=rows, test_prefixes=(("pytest",),))
    assert answer["state"] == "passed" and run.current_node_id == "fix"  # reported, not advanced
    assert run.context["octryx_children"]["agent-7"]["tool_calls"] == 1


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
