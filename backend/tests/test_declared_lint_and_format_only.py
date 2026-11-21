"""Lint before push, formatting fixes of confirmed tests, not-applicable is no failure.

A run can push and open a PR and then fail Bitbucket CI on lint (``flake8`` E501 in a new test helper of the
confirmed test file). Three problems, each closed:

(a) the repository's declared lint command never ran before the push — now the closed check ``lint_passed``
    (``workspace/declared_lint``) runs it fresh in the run's copy through the execution runtime: in a phase turn a
    finding in the run's change gets the checks reminder; in the green gate it fails the gate before review and push;
    a linter that cannot start pauses ``environment_not_ready``;
(b) implement refused every write to a confirmed test file, so the lint fix was impossible — now a write whose new
    content keeps the file's Python syntax tree identical passes (``format_only``) and the file stays intact; any
    other change stays refused;
(c) the review gate failed on ``test_command_passed`` = not applicable — not applicable is now neither pass nor fail
    (a gate none of whose blocking checks could be judged still fails).

Real paths: ``run_agent`` with a scripted model, the turn-end checks guard into ``record_phase_turn`` and the engine's
gate, the reviewer runner, and the workspace edit tools with their write decision.
"""

from __future__ import annotations

import copy

import pytest

from app.agent.engine import run_agent
from app.agent.loops.response._loop_workflow_checks import REMINDER_MARKER
from tests.declared_lint_and_format_only_support import (  # noqa: F401
    LONG,
    TEST_FILE,
    _copy,
    _gate_definition,
    _kinds,
    _server_pipeline,
    _started,
)
from tests.phased_workflow_fixtures import PHASE
from tests.test_phase_test_evidence_full_result import _model
from tests.test_workflow_run_pause import _turn
from tests.turn_preparation_support import prepare_chat_turn

LINT = {"type": "lint_passed", "params": {}, "blocking": True, "description": "The declared lint passes"}


def _tests_first_definition() -> dict:
    phase = copy.deepcopy(PHASE)
    phase["workflow_id"] = phase["workflow_class"] = "tdd_tests_first"  # a coding phase, no step plan
    contract = phase["workflow_contract"]
    contract.update(workflow_id="tdd_tests_first", workflow_class="tdd_tests_first", capability_class="change",
                    checks=[dict(LINT)], path_rules={"write": ["tests/**"]})
    phase["tool_policy"]["allowlist"] = ["analyze_workspace_repository", "read_workspace_file", "write_workspace_file"]
    return {"execution_kind": "phased",
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "tests_first", "type": "phase", "label": "Tests first", "config": phase},
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
            "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "tests_first"},
                      {"id": "2", "source_node_id": "tests_first", "target_node_id": "done"}]}


def _write(content: str) -> dict:
    import json

    return {"content": "", "tool_calls": [{"id": f"w{len(content)}", "function": {
        "name": "write_workspace_file", "arguments": json.dumps({"path": TEST_FILE, "content": content})}}]}


async def _lint_with_output(db, tmp_path, monkeypatch, output):
    from app.services.workflow_runs.workspace import declared_lint

    root = tmp_path / "copy"
    _admin, _session, run = await _started(db, _gate_definition([LINT]), _copy(root))
    (root / "src" / "textkit.py").write_text("VALUE = 1\n")  # changed against the base

    async def execution(*_args, **_kwargs):
        return 1, output(root), "", {"provider": "host"}

    monkeypatch.setattr(declared_lint, "_execute", execution)
    return await declared_lint.declared_lint_run(db, run)


# (a) lint before push --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_lint_finding_in_the_change_fails_the_green_gate_before_the_push(db, tmp_path):
    root = tmp_path / "copy"
    _admin, session, run = await _started(db, _gate_definition([LINT]), _copy(root))
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n" + LONG)

    await _turn(db, session.id, ["knowledge_search"])

    gate = run.gate_results["green"]
    assert gate["state"] == "failed" and run.current_node_id == "implement", gate  # back to the fix, never pushed
    assert f"src/textkit.py:2: E501 line too long ({len(LONG) - 1} > 79)" in gate["results"][0]["detail"]
    assert "legacy.py" not in gate["results"][0]["detail"]  # a base finding outside the change decides nothing

    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return ' '.join(text.split()[:count])\n")
    await _turn(db, session.id, ["knowledge_search"])
    assert (run.status, run.outcome) == ("completed", "done"), run.gate_results
    assert "did not change" in run.gate_results["green"]["results"][0]["detail"]  # the base finding, noted


@pytest.mark.asyncio
async def test_a_declared_linter_that_cannot_start_pauses_environment_not_ready(db, tmp_path):
    root = tmp_path / "copy"
    _admin, session, run = await _started(db, _gate_definition([LINT]), _copy(root, lint="nolint-xyz ."))
    (root / "src" / "textkit.py").write_text("def truncate_words(text, count):\n    return text[:count]\n")

    await _turn(db, session.id, ["knowledge_search"])

    assert (run.status, run.pause_reason) == ("paused", "environment_not_ready"), run.node_state
    message = run.node_state["pause"]["message"]
    assert message.startswith("The declared lint command could not run") and "nolint-xyz" in message
    assert run.current_node_id == "green"  # paused at the gate: no loop taken
    assert (await _kinds(db, run)).count(("node_entered", "implement")) == 1


@pytest.mark.asyncio
async def test_a_lint_finding_in_a_phase_turn_gets_the_reminder_and_the_fix_passes(db, tmp_path, monkeypatch):
    root = tmp_path / "copy"
    admin, session, run = await _started(db, _tests_first_definition(), _copy(root))
    prompt = "Write the failing test for truncate_words."
    session, _runtime, _thinking, _agent = await prepare_chat_turn(db=db, user=admin, prompt=prompt,
                                                                   session_id=session.id)
    await db.commit()
    long_test = "def test_truncate_words_joins_kept_words():\n" + LONG
    short_test = "def test_truncate_words_joins_kept_words():\n    assert truncate_words('a b c', 2) == 'a b'\n"
    done = {"content": "The new test is written."}
    analyze = {"content": "", "tool_calls": [{"id": "a1", "function": {"name": "analyze_workspace_repository",
                                                                      "arguments": "{}"}}]}
    seen = _model(monkeypatch, [analyze, _write(long_test), done, _write(short_test), done])

    async for _event in run_agent(session_id=session.id, user_message=prompt, user_id=admin.id, project_id=None,
                                  agent_type=session.agent_type, db=db):
        pass
    await db.refresh(run)

    reminder = [str(m.get("content")) for m in seen[3] if str(m.get("content") or "").startswith(REMINDER_MARKER)]
    assert reminder and "tests/test_textkit.py:2: E501" in reminder[0], seen[3][-2:]
    assert len(seen) == 5 and (root / TEST_FILE).read_text() == short_test
    assert (run.status, run.outcome) == ("completed", "done"), run.gate_results
    assert [kind for kind, _node in await _kinds(db, run)].count("phase_turn") == 1


@pytest.mark.asyncio
async def test_an_absolute_linter_path_for_a_changed_file_cannot_pass(db, tmp_path, monkeypatch):
    # Ported from Codex's repro.
    result = await _lint_with_output(db, tmp_path, monkeypatch,
                                     lambda root: f"{root}/src/textkit.py:1: E501 line too long\n")
    assert result["state"] == "failed" and "src/textkit.py:1" in result["reason"], result


@pytest.mark.asyncio
async def test_an_absolute_path_in_an_untouched_baseline_file_stays_a_note(db, tmp_path, monkeypatch):
    result = await _lint_with_output(db, tmp_path, monkeypatch,
                                     lambda root: f"{root}/src/legacy.py:1:80: E501 line too long (100 > 79)\n")
    assert result["state"] == "passed" and "did not change" in result["note"], result


@pytest.mark.asyncio
async def test_a_finding_the_copy_cannot_place_fails_closed(db, tmp_path, monkeypatch):
    result = await _lint_with_output(db, tmp_path, monkeypatch,
                                     lambda _root: "/elsewhere/textkit.py:1: E501 line too long\n")
    assert result["state"] == "failed" and "outside the run's working copy" in result["reason"], result
