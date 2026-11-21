"""Review fixes of S7/S10: a device run's change is what the reviewer reviews and exactly what the platform pushes.

The octryx-claude launcher reports the working copy as a patch against the run's base, untracked files included
(the review found new files invisible to the reviewer); the server applies it to its own working copy of the run's
branch, the reviewer reviews that copy, and ``scm.push`` pushes only the reviewed tree (the review found the server
would push its own, unchanged copy). A device run without a reviewed change is never pushed.
"""

from __future__ import annotations

import copy
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.octryx.stop import run_stop
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.review.runner import run_due_reviews
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import PHASE
from tests.workflow_run_octryx_support import _bound_run, _call
from tests.workflow_run_review_support import PASS, ScriptedReviewer


def _git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, env=env).stdout.strip()


def _definition() -> dict:
    fix = copy.deepcopy(PHASE)
    fix["workflow_contract"].update(capability_class="change", path_rules={"protect_confirmed_tests": True},
                                    checks=[{"type": "tool_called", "params": {"tools": ["run_test_suite"]},
                                             "blocking": True, "description": "The tests ran"}])
    fix["tool_policy"]["allowlist"] = ["read_workspace_file", "edit_workspace_file", "run_test_suite"]
    return {"execution_kind": "phased",
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "fix", "type": "phase", "label": "Fix", "config": fix},
                      {"id": "independent_review", "type": "review", "label": "Independent review"},
                      {"id": "review", "type": "gate", "config": {"phase": "fix", "checks": [
                          {"type": "review_passed", "params": {}, "blocking": True, "description": "Reviewed"}]}},
                      {"id": "push", "type": "platform_action", "label": "Push", "config": {"action": "scm.push"}},
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
                      {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
            "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "fix"},
                      {"id": "2", "source_node_id": "fix", "target_node_id": "independent_review"},
                      {"id": "3", "source_node_id": "independent_review", "target_node_id": "review"},
                      {"id": "4", "source_node_id": "review", "target_node_id": "push", "when": "passed"},
                      {"id": "5", "source_node_id": "push", "target_node_id": "done", "when": "succeeded"},
                      {"id": "6", "source_node_id": "push", "target_node_id": "blocked", "when": "failed"}]}


def _repos(tmp_path: Path) -> tuple[Path, Path, str]:
    server = tmp_path / "server"
    (server / "pay").mkdir(parents=True)
    (server / "pay" / "totals.py").write_text("def total(x):\n    return int(x)\n")
    _git(server, "init", "-q", "-b", "main")
    _git(server, "add", "-A")
    _git(server, "commit", "-q", "-m", "base")
    device = tmp_path / "device"
    _git(tmp_path, "clone", "-q", str(server), str(device))
    return server, device, _git(server, "rev-parse", "HEAD")


def _device_patch(device: Path, base: str) -> str:
    """What the launcher reports: everything against the base, new files included (a temporary index)."""
    env = {**os.environ, "GIT_INDEX_FILE": str(device / ".git" / "facts-index")}
    _git(device, "read-tree", "HEAD", env=env)
    _git(device, "add", "-A", env=env)
    return _git(device, "diff", "--cached", "--binary", base, env=env) + "\n"


class Pushes:
    """The SCM push tool: commits the staged working copy and reports the commit it pushed."""

    def __init__(self, monkeypatch):
        self.commits: list[str] = []

        async def dispatch(db, run, tool, arguments, *, capability_class):
            path = Path(arguments["local_path"])
            _git(path, "commit", "-q", "-m", arguments["commit_message"])
            self.commits.append(_git(path, "rev-parse", "HEAD"))
            return read_outcome({"status": "pushed", "head_commit": self.commits[-1]})

        monkeypatch.setattr(scm, "dispatch_tool", dispatch)


@pytest.mark.asyncio
async def test_the_device_change_with_its_new_files_is_reviewed_and_exactly_that_tree_is_pushed(
        db, tmp_path, monkeypatch):
    pushes = Pushes(monkeypatch)
    server, device, base = _repos(tmp_path)
    run, gateway, _key, _workspace_id = await _bound_run(db, _definition())
    run.repository, run.branch = "github:acme/pay", "bugfix/PAY-1-totals"
    run.context = {**run.context, "local_path": str(server), "base_sha": base}
    (device / "pay" / "totals.py").write_text("def total(x):\n    return round_half_up(x)\n")
    (device / "pay" / "rounding.py").write_text("def round_half_up(x):\n    return int(x + 0.5)\n")  # untracked

    at = utc_now() + timedelta(seconds=5)
    facts = {"node_id": "fix", "entry": run.node_state["entry"],
             "change": {"base": base, "patch": _device_patch(device, base)}}
    answer = await run_stop(db, session=gateway, hook_input={"workflow_run_facts": facts}, tool_calls=[
        _call(gateway, "Bash", at=at, command="pytest -q", excerpt="tests/test_totals.py::test_half PASSED")],
        test_prefixes=(("pytest",),))
    assert answer["state"] == "passed" and run.waiting_kind == "awaiting_review"
    await db.commit()

    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert "+def round_half_up(x):" in reviewer.tasks[0][1]  # the new file is part of what was reviewed
    run = await db.get(WorkflowRun, run.id)
    assert (run.status, run.outcome) == ("completed", "done")
    reviewed = run.context["review"]["tree"]
    assert _git(server, "rev-parse", f"{pushes.commits[0]}^{{tree}}") == reviewed  # pushed == reviewed
    assert run.context["head_sha"] == pushes.commits[0]
    assert (server / "pay" / "rounding.py").exists()

    # The working copy moved on after the review: the push refuses instead of pushing an unreviewed change.
    (server / "pay" / "late.py").write_text("x = 1\n")
    refused = await scm.push(db, run, {})
    assert refused.state == "failed" and "no longer the change the reviewer reviewed" in refused.reason


@pytest.mark.asyncio
async def test_a_device_run_without_a_reviewed_change_is_never_pushed(db, tmp_path, monkeypatch):
    Pushes(monkeypatch)
    server, _device, base = _repos(tmp_path)
    run, _gateway, _key, _workspace_id = await _bound_run(db, _definition())
    run.repository, run.branch = "github:acme/pay", "bugfix/PAY-1-totals"
    run.context = {**run.context, "local_path": str(server), "base_sha": base}
    refused = await scm.push(db, run, {})
    assert refused.state == "failed" and "a device run pushes only the change" in refused.reason


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
