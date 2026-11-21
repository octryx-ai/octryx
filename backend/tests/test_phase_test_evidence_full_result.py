"""The workflow checks judge a test run by its FULL result, never the model's compacted copy.

A declared runner can run in the copy's .venv — fresh JUnit, 11 passed and 4 failed on AssertionError — while the
turn's tool history keeps only the model-facing result (``_loop_tools._history_result_for_prompt``; the harness's
``compact_result``), hard-capped for ``run_test_suite`` without output or report; ``reclassify`` would then see no
executed test, drop the call and report "The test suite ran — not called: run_test_suite". So the history entry of
an evidence tool also carries its full result (``workflow_checks.evidence.FULL_RESULT_KEY``) and the checks read
that; an entry with only the compacted copy is not verified, never invented.

Real path: turn preparation on a session bound to a running phased run (change phase, run working copy), then
``run_agent`` with a scripted model that calls ``run_test_suite``; the declared command runs in the copy's .venv with a
result large enough to be compressed for the model.
"""

from __future__ import annotations

import copy
import sys

import pytest

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.services.workflow_checks.evidence import FULL_RESULT_KEY, MISSING_FULL_RESULT, tool_uses, turn_evidence
from app.services.workflow_checks.library import evaluate_checks
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from tests.declared_test_run_support import DECLARED, _venv
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.test_phase_working_copy import _commit_all
from tests.turn_preparation_support import prepare_chat_turn

CASES = 300  # parametrized cases: the result is far beyond the model-facing budget
TOOL_CALL = {"content": "", "tool_calls": [{"id": "call-tests", "function": {"name": "run_test_suite",
                                                                              "arguments": "{}"}}]}
FINAL = {"content": "The new tests fail as expected; the existing ones pass."}
RAN_CHECK = {"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "blocking": True,
             "description": "The test suite ran"}


def _definition() -> dict:
    definition = copy.deepcopy(phased_definition())
    config = definition["nodes"][1]["config"]
    config["workflow_contract"]["capability_class"] = "change"
    config["workflow_contract"]["checks"] = [dict(RAN_CHECK)]
    config["tool_policy"]["allowlist"] = ["read_workspace_file", "write_workspace_file", "run_test_suite"]
    return definition


def _model(monkeypatch, replies: list[dict]) -> list[list[dict]]:
    seen: list[list[dict]] = []

    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

    async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None, **_kwargs):
        seen.append(list(messages))
        reply = replies.pop(0)
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return {"tool_calls": None, "model": "anthropic.claude-sonnet-4-5", **reply, "usage": usage}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)
    return seen


async def _run_with_copy(db, tmp_path):
    from app.services.workflow_runs.records import new_chat_session, start_run

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition()),
                          project_id=workspace_id, session=session)
    root = tmp_path / "run-copy"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_textkit.py").write_text(
        "import pytest\n\n\n"
        f"@pytest.mark.parametrize('case', range({CASES}))\n"
        "def test_existing_behaviour_keeps_working(case):\n    assert True\n\n\n"
        "def test_truncate_words_joins_kept_words():\n    assert 'truncate_words' == 'missing'\n")
    _commit_all(root)
    _venv(root, sys.executable)
    run.context = {**dict(run.context or {}), "local_path": str(root), "base_sha": "HEAD",
                   PREPARATION_KEY: {"state": "ready", "runtime": "server", "spec": {"environment": DECLARED}}}
    await db.commit()
    return admin, session, run


@pytest.mark.asyncio
async def test_a_compressed_test_result_still_reports_its_red_run_to_the_phase(db, tmp_path, monkeypatch):
    admin, session, run = await _run_with_copy(db, tmp_path)
    prompt = "Run the tests."
    session, _runtime, _thinking, _agent = await prepare_chat_turn(db=db, user=admin, prompt=prompt,
                                                                   session_id=session.id)
    await db.commit()
    seen = _model(monkeypatch, [TOOL_CALL, FINAL])

    async for _event in run_agent(session_id=session.id, user_message=prompt, user_id=admin.id, project_id=None,
                                  agent_type=session.agent_type, db=db):
        pass
    await db.refresh(run)

    tool_message = next(m for m in seen[1] if m.get("role") == "tool")
    content = str(tool_message.get("content") or "")
    # The model gets the compressed copy (hard-capped, as in a real run).
    assert '"_hard_capped": true' in content and "test_existing_behaviour_keeps_working" not in content
    result = dict(run.gate_results or {}).get("work") or {}
    assert result.get("state") == "passed", run.gate_results  # "The test suite ran": the full result counted
    runs = dict(run.context.get("tests") or {}).get("runs") or []
    assert runs, run.context.get("tests")
    outcomes = dict(runs[-1].get("results") or {})
    failed = [test_id for test_id, value in outcomes.items() if value.get("outcome") == "failed"]
    assert failed == ["tests/test_textkit.py::test_truncate_words_joins_kept_words"]
    assert sum(1 for value in outcomes.values() if value.get("outcome") == "passed") == CASES


def test_a_history_entry_with_only_the_compacted_copy_is_not_verified():
    compacted = {"_hard_capped": True, "keys": ["stdout", "test_report"], "preview": "15 passed",
                 "_prompt_result_source": "compact_result"}
    history = [{"tool_name": "run_test_suite", "params": {}, "result": compacted}]

    uses = tool_uses(history)
    assert uses[0].succeeded is False and uses[0].result["error"] == MISSING_FULL_RESULT
    evidence = turn_evidence(history)
    assert evidence.test_runs == []
    assert [result.outcome for result in evaluate_checks([RAN_CHECK], evidence)] == ["failed"]


def test_the_full_result_on_the_entry_is_what_the_checks_judge():
    full = {"exit_code": 1, "all_green": False, "command": "python -m pytest -v tests/",
            "stdout": "tests/test_a.py::test_new FAILED\ntests/test_a.py::test_old PASSED\n1 failed, 1 passed in 0.1s",
            "stderr": "", "failed_tests": ["tests/test_a.py::test_new"]}
    history = [{"tool_name": "run_test_suite", "params": {}, "result": {"_hard_capped": True},
                FULL_RESULT_KEY: full}]

    evidence = turn_evidence(history)

    assert [result.outcome for result in evaluate_checks([RAN_CHECK], evidence)] == ["passed"]
    assert evidence.test_runs[0]["results"]["tests/test_a.py::test_new"]["outcome"] == "failed"
    # Other tools keep their history as it was.
    assert tool_uses([{"tool_name": "read_workspace_file", "result": {"_hard_capped": True}}])[0].succeeded is True



@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
