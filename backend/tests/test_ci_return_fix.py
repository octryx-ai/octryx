"""After CI failed on the pushed commit, the fix phase must fix that failure."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Session, WorkflowRunEvent
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.watch import record_condition
from tests.declared_lint_and_format_only_support import _copy, _started
from tests.phased_workflow_fixtures import PHASE
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

TEST_FILE = "tests/test_textkit.py"
FAILING = "tests/test_textkit.py::test_truncate_words_joins_kept_words"


def _definition() -> dict:
    implement = copy.deepcopy(PHASE)
    tool = {"type": "tool_called", "params": {"tools": ["knowledge_search"]}, "blocking": True, "description": "Ran"}
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "ci", "type": "watch", "label": "CI on the pushed commit",
                   "config": {"conditions": ["ci.succeeded", "ci.failed"], "advance": "auto"}},
                  {"id": "implement", "type": "phase", "label": "Implement", "config": implement},
                  {"id": "green", "type": "gate", "config": {"phase": "implement", "checks": [tool]}},
                  {"id": "push", "type": "platform_action", "label": "Push", "config": {"action": "scm.push"}},
                  {"id": "action_failed", "type": "pause", "label": "A step failed",
                   "config": {"reason": "action_failed"}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
                  {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "ci"},
                  {"id": "2", "source_node_id": "ci", "target_node_id": "done", "when": "ci.succeeded"},
                  {"id": "loop-ci", "source_node_id": "ci", "target_node_id": "implement", "when": "ci.failed",
                   "kind": "loop", "max_iterations": 2},
                  {"id": "4", "source_node_id": "implement", "target_node_id": "green"},
                  {"id": "5", "source_node_id": "green", "target_node_id": "push", "when": "passed"},
                  {"id": "6", "source_node_id": "green", "target_node_id": "implement", "when": "failed",
                   "kind": "loop", "max_iterations": 3},
                  {"id": "7", "source_node_id": "push", "target_node_id": "ci", "when": "succeeded"},
                  {"id": "8", "source_node_id": "push", "target_node_id": "action_failed", "when": "failed"},
                  {"id": "9", "source_node_id": "action_failed", "target_node_id": "blocked"}],
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _pushing(monkeypatch) -> list[str]:
    pushed: list[str] = []

    async def dispatch(db, run, tool, arguments, *, capability_class, workspace_root=None):
        root = Path(arguments["local_path"])
        if not _git(root, "status", "--porcelain"):
            return read_outcome({"status": "no_changes"})
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", arguments["commit_message"])
        pushed.append(_git(root, "rev-parse", "HEAD"))
        return read_outcome({"status": "pushed", "head_commit": pushed[-1]})

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    monkeypatch.setattr(dispatch_module, "dispatch_tool", dispatch)
    return pushed


async def _ci_red(db, tmp_path, *, test_file: str, ci_tests: dict | None = None):
    root = tmp_path / "copy"
    context = _copy(root)
    (root / TEST_FILE).write_text(test_file)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "the pushed change")
    head = _git(root, "rev-parse", "HEAD")
    context.update(base_sha=_git(root, "rev-parse", "HEAD~1"), head_sha=head)
    _admin, session, run = await _started(db, _definition(), context)
    run.repository, run.branch, run.ticket_key = "bitbucket:PAY/payments", "feature/BRD-12", "BRD-12"
    run.context = {**run.context, "ci": {"provider": "bitbucket", "state": "failed", "url": "https://ci.test/9",
                                         "tests": dict(ci_tests or {}), "sha": head}}
    assert (run.status, run.current_node_id) == ("waiting", "ci")
    assert await record_condition(db, run, "ci.failed", source="test")
    await db.commit()
    assert (run.status, run.current_node_id) == ("running", "implement")
    return run, session, root


async def _turn_end(db, session_id: str, history: list[dict] | None = None) -> str | None:
    from tests.phase_turn_support import finish_phase_turn

    resolution = await run_turn_resolution(db, await db.get(Session, session_id), user_message="Fix CI.")
    return await finish_phase_turn(db, session_id, resolution,
                                   [{"tool_name": "knowledge_search", "status": "success", "result": {}},
                                    *(history or [])], content="Fixed.")


async def _kinds(db, run) -> list[tuple[str, str]]:
    return [(event.kind, event.node_id) for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]


def _suite(outcome: str) -> dict:
    return {"tool_name": "run_test_suite", "status": "success", "result": {
        "stdout": f"{FAILING} {outcome.upper()}\n", "exit_code": 0 if outcome == "passed" else 1,
        "all_green": outcome == "passed"}}


@pytest.mark.asyncio
async def test_failing_ci_tests_must_pass_fresh_in_the_fix_turn(db, tmp_path, monkeypatch):
    _pushing(monkeypatch)
    run, session, root = await _ci_red(db, tmp_path, test_file="def test_truncate_words_joins_kept_words():\n"
                                                                "    assert True\n", ci_tests={FAILING: "failed"})
    # A fix turn whose run still shows the failing CI test does not pass the phase.
    assert await _turn_end(db, session.id, [_suite("failed")]) == "not_verified"
    assert FAILING in str(run.gate_results["implement"])
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return text\n\n\nFIXED = 1\n")
    assert await _turn_end(db, session.id, [_suite("passed")]) == "passed"
    assert run.gate_results["implement"]["state"] == "passed"


@pytest.mark.asyncio
async def test_a_push_with_nothing_new_after_a_red_ci_returns_to_the_fix_within_the_ci_budget(
        db, tmp_path, monkeypatch):
    # The failed CI test passes fresh: the phase passes, but there is nothing to push.
    _pushing(monkeypatch)
    run, session, _root = await _ci_red(db, tmp_path, test_file="def test_truncate_words_joins_kept_words():\n"
                                                                 "    assert True\n", ci_tests={FAILING: "failed"})

    assert await _turn_end(db, session.id, [_suite("passed")]) == "passed"
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "implement"), run.node_state
    assert run.outcome is None and run.loop_counters["loop-ci"]["used"] == 2
    action = run.context["actions"]["push"]
    assert action["result"] == "ci_return" and "not fixed yet" in action["reason"]
    assert ("action_failure_not_recoverable", "action_failed") not in await _kinds(db, run)

    # the CI loop budget is spent: the loop pauses, never blocked
    assert await _turn_end(db, session.id, [_suite("passed")]) == "passed"
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "loop_limit") and run.outcome is None


@pytest.mark.asyncio
async def test_a_push_with_nothing_new_and_no_red_ci_fails_as_before(db, tmp_path, monkeypatch):
    _pushing(monkeypatch)
    run, session, _root = await _ci_red(db, tmp_path, test_file="def test_ok():\n    assert True\n")
    run.context = {key: value for key, value in run.context.items() if key != "ci"}
    await db.commit()

    assert await _turn_end(db, session.id) == "passed"
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert run.context["actions"]["push"]["reason"] == "nothing to push: the working copy has no change"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
