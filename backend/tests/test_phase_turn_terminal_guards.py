"""Every guard that ends a phase turn still reports the phase result, once.

A declared runner can run twice with a correct fresh red (11 passed, 4 failed on AssertionError) while the closing
reply says what comes next, so the coding narration guard reminds, then replaces the final message with "Agent
stopped because the run kept describing the next coding step instead of executing it"
(``loop.coding.narration_stop``). That guard runs before the workflow checks; returning early there would leave the
phase result unrecorded, and so would an ended-turn record wired only for the citation refusal and the reply-contract
stop.

So (``_loop_workflow_checks``):

1. every terminal guard outcome of ``handle_response_guards`` (transitions, coding, follow-up, answer evidence,
   reply contract) records the turn's checks through the shared path (``record_if_turn_ended`` →
   ``record_phase_turn``), and every record path records **once per turn** (``claim_turn_checks_record``);
2. a phase turn whose phase's required tool evidence already exists this turn (``phase_tool_evidence_present``) is not
   "intent only" for the narration guard. Normal coding chat keeps the guard
   (``test_run_agent_domain_coverage_a``'s intent-only stop tests run unchanged).

Real path: turn preparation on a session bound to a running phased run, then ``run_agent`` with a scripted model.
"""

from __future__ import annotations

import copy
import sys

import pytest
from sqlalchemy import select

import app.agent.loops.response._loop_response_guards as response_guards
from app.agent.core.runtime.turn_execution_binding import (
    bind_turn_execution_snapshot,
    claim_turn_checks_record,
    clear_turn_execution_snapshot,
)
from app.agent.engine import run_agent
from app.agent.loops.response._loop_workflow_checks import record_checks_for_ended_turn
from app.models import TurnTrace, WorkflowRunEvent
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.test_runs import confirm_tests, snapshot_confirmed_tests
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from tests.declared_test_run_support import DECLARED, _venv
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.test_phase_test_evidence_full_result import RAN_CHECK, TOOL_CALL, _model
from tests.test_phase_turn_answer_evidence import CITED, SEARCH_CALL
from tests.test_phase_turn_answer_evidence import _phase_turn as _knowledge_phase_turn
from tests.test_phase_working_copy import _commit_all
from tests.turn_preparation_support import prepare_chat_turn

NEW_TEST = "tests/test_textkit.py::test_truncate_words_joins_kept_words"
# A real closing reply: a correct red report that also says what comes next ("Next I will …").
NARRATION = ("The suite is red as required: test_truncate_words_joins_kept_words fails on an AssertionError and the "
             "existing tests pass. Next I will implement truncate_words in the Implement phase.")
NARRATION_STOP = "kept describing the next coding step"


def _tdd_definition() -> dict:
    tests_first = copy.deepcopy(PHASE)
    tests_first["workflow_id"] = tests_first["workflow_class"] = "tdd_tests_first"  # a coding phase (not knowledge), no step plan
    contract = tests_first["workflow_contract"]
    contract.update(workflow_id="tdd_tests_first", workflow_class="tdd_tests_first", capability_class="change")
    contract["checks"] = [dict(RAN_CHECK)]
    tests_first["tool_policy"]["allowlist"] = ["read_workspace_file", "write_workspace_file", "run_test_suite"]
    red = {"type": "tests_red", "params": {}, "blocking": True, "description": "The new tests fail first"}
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "tests_first", "type": "phase", "label": "Tests first", "config": tests_first},
                  {"id": "red", "type": "gate", "config": {"checks": [red]}},
                  {"id": "impl", "type": "phase", "label": "Implement", "config": copy.deepcopy(tests_first)},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "tests_first"},
                  {"id": "2", "source_node_id": "tests_first", "target_node_id": "red"},
                  {"id": "3", "source_node_id": "red", "target_node_id": "impl", "when": "passed"},
                  {"id": "4", "source_node_id": "red", "target_node_id": "tests_first", "when": "failed",
                   "kind": "loop", "max_iterations": 2},
                  {"id": "5", "source_node_id": "impl", "target_node_id": "done"}],
    }


async def _tests_first_turn(db, tmp_path, monkeypatch, replies: list[dict]):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _tdd_definition()),
                          project_id=workspace_id, session=session)
    root = tmp_path / "run-copy"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_textkit.py").write_text(
        "def test_existing_behaviour_keeps_working():\n    assert True\n\n\n"
        "def test_truncate_words_joins_kept_words():\n    assert 'truncate_words' == 'missing'\n")
    _commit_all(root)
    _venv(root, sys.executable)
    run.context = {**dict(run.context or {}), "local_path": str(root), "base_sha": "HEAD",
                   PREPARATION_KEY: {"state": "ready", "runtime": "server", "spec": {"environment": DECLARED}}}
    confirm_tests(run, [NEW_TEST])
    await snapshot_confirmed_tests(db, run)
    await db.commit()
    prompt = "Write the failing tests for the item, then run them."
    session, _runtime, _thinking, _agent = await prepare_chat_turn(db=db, user=admin, prompt=prompt,
                                                                   session_id=session.id)
    await db.commit()
    seen = _model(monkeypatch, replies)
    contents: list[str] = []
    async for event in run_agent(session_id=session.id, user_message=prompt, user_id=admin.id, project_id=None,
                                 agent_type=session.agent_type, db=db):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    await db.refresh(run)
    kinds = [(event.kind, event.node_id) for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    return run, seen, contents, kinds, [dict(trace.raw_output or {}) for trace in traces]


@pytest.mark.asyncio
async def test_a_red_tests_first_turn_with_closing_narration_reaches_the_red_gate(db, tmp_path, monkeypatch):
    run, seen, contents, kinds, raw = await _tests_first_turn(
        db, tmp_path, monkeypatch, [TOOL_CALL, {"content": NARRATION}, {"content": NARRATION}])

    # The phase's required evidence (run_test_suite) exists: the closing reply is a report, not "intent only".
    assert len(seen) == 2, "the test call, then the accepted closing reply"
    assert not any(item.get("suppressed_for_coding_intent_only") for item in raw)
    assert NARRATION_STOP not in contents[-1] and "Next I will implement" in contents[-1]
    # Recorded once; the red gate evaluated the fresh red and the run moved on.
    assert kinds.count(("phase_turn", "tests_first")) == 1
    assert dict(run.gate_results or {})["tests_first"]["state"] == "passed", run.gate_results
    assert dict(run.gate_results or {})["red"]["state"] == "passed", run.gate_results
    assert run.current_node_id == "impl"


@pytest.mark.asyncio
async def test_the_real_narration_stop_of_a_phase_turn_records_its_result_once(db, tmp_path, monkeypatch):
    # No test ran: the narration guard still applies, stops the turn and the run gets one not_verified result.
    talk = {"content": "I will run the test suite now and then report the result."}
    run, seen, contents, kinds, raw = await _tests_first_turn(db, tmp_path, monkeypatch, [talk, talk, talk])

    assert NARRATION_STOP in contents[-1], contents
    assert any(item.get("stalled_on_coding_intent_only") for item in raw)
    assert len(seen) == 2
    assert kinds.count(("phase_turn", "tests_first")) == 1
    assert dict(run.gate_results or {})["tests_first"]["state"] == "not_verified", run.gate_results
    assert ("gate_evaluated", "red") not in kinds and run.current_node_id == "tests_first"


def _terminal(name: str):
    async def guard(inputs=None, /, **kwargs):
        # The loop entry guards take their inputs dataclass, the others take keywords.
        kwargs = vars(inputs) if inputs is not None else kwargs
        counts = {key: value for key, value in kwargs.items() if key.startswith("consecutive_")}
        if kwargs.get("tool_calls"):
            return None if name in {"handle_answer_evidence_guard", "handle_reply_contract_check"} else {
                "action": "none", **counts}
        return {"action": "return", "yield_content": f"stopped by {name}", "yield_model": kwargs["usage_model"],
                **counts}

    return guard


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["handle_transition_response_guards", "handle_coding_response_guards",
                                   "handle_followup_response_guards", "handle_answer_evidence_guard",
                                   "handle_reply_contract_check"])
async def test_every_terminal_guard_records_the_phase_result_once(db, monkeypatch, guard):
    monkeypatch.setattr(response_guards, guard, _terminal(guard))
    run, seen, contents, _records, _stored, kinds = await _knowledge_phase_turn(
        db, monkeypatch, [SEARCH_CALL, {"content": CITED}])

    assert len(seen) == 2 and contents[-1] == f"stopped by {guard}"
    assert kinds.count(("phase_turn", "work")) == 1
    assert dict(run.gate_results or {})["work"]["state"] == "passed", run.gate_results
    assert ("gate_evaluated", "verify") in kinds


@pytest.mark.asyncio
async def test_a_turn_records_its_checks_once_whichever_paths_try(db):
    from tests.phased_workflow_fixtures import phased_definition

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=session)
    await db.commit()
    resolution = await run_turn_resolution(db, session, user_message="Work.")
    turn = {"db": db, "session_id": session.id, "messages": [], "context_snapshot": {}, "content": "Done.",
            "request_analysis": {ROUTING_RESOLUTION_KEY: resolution}, "turn_tool_history": [],
            "sub_agent_depth": 0}
    bind_turn_execution_snapshot(session.id, {})
    try:
        await record_checks_for_ended_turn(**turn)
        await record_checks_for_ended_turn(**turn)  # a second terminal path in the same turn
        assert claim_turn_checks_record(session.id) is False
        bind_turn_execution_snapshot(session.id, {})  # the next turn records again
        assert claim_turn_checks_record(session.id) is True
    finally:
        clear_turn_execution_snapshot(session.id)
    kinds = [event.kind for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]
    assert kinds.count("phase_turn") == 1


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
