"""After CI failed on the pushed commit, the fix phase must fix that failure.

Without this, CI could fail on lint (E501), the ``ci.failed`` loop return to implement, the model's fix be refused,
yet implement and green pass without a change, the review pass the same tree and the push answer "nothing to
push" — classed not recoverable, the run would end ``blocked``. With ``workflow_runs/ci_return``:

- while the pushed commit's CI failure is pending, a turn of the phase the CI loop returned to passes only on fresh
  evidence that the failure is fixed (``ci_findings_addressed``): the failing CI tests pass in the turn's test run,
  or — CI failed outside the tests — the declared lint passes fresh on the copy; the reminder names the finding;
- a push with nothing new while that failure is pending returns to the fix phase through the ``ci.failed`` loop edge
  (bounded by the CI loop budget), never ``blocked``; a push with nothing new elsewhere fails.

Real run path: the CI watch's ``ci.failed`` (``watch.record_condition``) → the fix phase's turn end (the real checks
guard → ``record_phase_turn``) → the green gate → ``scm.push`` through the platform action and the engine's routing.
The provider's push tool is replaced by a local commit (it reports the new head or ``no_changes``).
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.loops.response._loop_workflow_checks import REMINDER_MARKER, handle_workflow_checks_guard
from app.models import Session, WorkflowRunEvent
from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.watch import record_condition
from tests.declared_lint_and_format_only_support import LONG, _copy, _started
from tests.phased_workflow_fixtures import PHASE

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
    """The provider's push tool: a local commit of the copy's change (``no_changes`` when there is none)."""
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
    """A run whose pushed commit (the copy's HEAD, with ``test_file``) failed CI; the watch takes ``ci.failed``."""
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


async def _turn_end(db, session_id: str, messages: list[dict], history: list[dict] | None = None):
    """The fix phase's turn end: the real checks guard with the turn's own tool calls."""
    resolution = await run_turn_resolution(db, await db.get(Session, session_id), user_message="Fix CI.")

    async def persist_turn_trace(**_kwargs):
        return None

    with prompt_set_scope(seed_prompt_set()):
        return await handle_workflow_checks_guard(
            db=db, session_id=session_id, runtime={"provider_name": "test"}, response={"usage": {}},
            request_messages=[], messages=messages, context_snapshot={}, runtime_attempts=[], runtime_settings={},
            usage_model="m", content="Fixed.", tool_calls=None, has_followup_steps=False, sub_agent_depth=0,
            request_analysis={ROUTING_RESOLUTION_KEY: resolution},
            turn_tool_history=[{"tool_name": "knowledge_search", "status": "success", "result": {}},
                               *(history or [])],
            persist_turn_trace=persist_turn_trace)


async def _kinds(db, run) -> list[tuple[str, str]]:
    return [(event.kind, event.node_id) for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]


LINT_RED = "def test_truncate_words_joins_kept_words():\n" + LONG
LINT_FIXED = ("def test_truncate_words_joins_kept_words():\n"
              "    assert truncate_words(\n        'one two three four five six seven', 2\n    ) == 'one two'\n")


@pytest.mark.asyncio
async def test_a_lint_red_ci_needs_the_lint_fixed_before_the_fix_phase_passes(db, tmp_path, monkeypatch):
    pushed = _pushing(monkeypatch)
    run, session, root = await _ci_red(db, tmp_path, test_file=LINT_RED)
    old_head = run.context["head_sha"]
    messages: list[dict] = []

    # Implement without a change: not passed; the reminder names the finding.
    assert await _turn_end(db, session.id, messages) == {"action": "continue"}
    reminder = messages[-1]["content"]
    assert reminder.startswith(REMINDER_MARKER) and "tests/test_textkit.py:2: E501" in reminder, reminder
    await _turn_end(db, session.id, messages)  # after the reminder: recorded, still not passed
    assert run.gate_results["implement"]["state"] == "not_verified" and run.current_node_id == "implement"

    # The AST-identical fix: the declared lint, fresh on the copy, no longer finds it → passes → pushed, new SHA.
    (root / TEST_FILE).write_text(LINT_FIXED)
    assert await _turn_end(db, session.id, []) is None
    await db.refresh(run)
    assert run.gate_results["implement"]["state"] == "passed", run.gate_results
    assert len(pushed) == 1 and run.context["head_sha"] == pushed[0] != old_head
    assert (run.current_node_id, run.status) == ("ci", "waiting") and "ci" not in run.context  # CI on the new SHA


@pytest.mark.asyncio
async def test_failing_ci_tests_must_pass_fresh_in_the_fix_turn(db, tmp_path, monkeypatch):
    _pushing(monkeypatch)
    run, session, root = await _ci_red(db, tmp_path, test_file="def test_truncate_words_joins_kept_words():\n"
                                                                "    assert True\n", ci_tests={FAILING: "failed"})
    suite = lambda outcome: {"tool_name": "run_test_suite", "status": "success", "result": {  # noqa: E731
        "stdout": f"{FAILING} {outcome.upper()}\n", "exit_code": 0 if outcome == "passed" else 1,
        "all_green": outcome == "passed"}}
    messages: list[dict] = []

    assert await _turn_end(db, session.id, messages, [suite("failed")]) == {"action": "continue"}
    assert FAILING in messages[-1]["content"]
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return text\n\n\nFIXED = 1\n")
    assert await _turn_end(db, session.id, [], [suite("passed")]) is None
    assert run.gate_results["implement"]["state"] == "passed"


@pytest.mark.asyncio
async def test_a_push_with_nothing_new_after_a_red_ci_returns_to_the_fix_within_the_ci_budget(
        db, tmp_path, monkeypatch):
    # CI failed outside the tests and the declared lint is clean: the phase passes, but there is nothing to push.
    _pushing(monkeypatch)
    run, session, _root = await _ci_red(db, tmp_path, test_file="def test_ok():\n    assert True\n")

    assert await _turn_end(db, session.id, []) is None
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "implement"), run.node_state  # back to the fix
    assert run.outcome is None and run.loop_counters["loop-ci"]["used"] == 2
    action = run.context["actions"]["push"]
    assert action["result"] == "ci_return" and "not fixed yet" in action["reason"]
    assert ("action_failure_not_recoverable", "action_failed") not in await _kinds(db, run)

    assert await _turn_end(db, session.id, []) is None  # the CI loop budget is spent: the loop pauses, never blocked
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "loop_limit") and run.outcome is None


@pytest.mark.asyncio
async def test_a_push_with_nothing_new_and_no_red_ci_fails_as_before(db, tmp_path, monkeypatch):
    _pushing(monkeypatch)
    run, session, _root = await _ci_red(db, tmp_path, test_file="def test_ok():\n    assert True\n")
    run.context = {key: value for key, value in run.context.items() if key != "ci"}  # no pending CI failure
    await db.commit()

    assert await _turn_end(db, session.id, []) is None
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert run.context["actions"]["push"]["reason"] == "nothing to push: the working copy has no change"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
