from __future__ import annotations

import json
import uuid
from typing import get_args

import pytest
from sqlalchemy import select

from app.models import ToolCall
from app.services.agent_gateway import contract
from app.services.agent_gateway.decision_confirmation import WORKFLOW_DECIDE_HOOK_TOOL
from app.services.agent_gateway.read_evidence import NATIVE_READ_EVIDENCE
from app.services.agent_gateway.stored_types import (
    ConfirmationTicketParameters,
    DecisionTicketParameters,
    ExecutionOutcome,
    GatewaySource,
    GatewayToolCallParameters,
    GatewayToolCallResult,
    HookDenialParameters,
    HookDenialResult,
    HookSource,
    HostedSearchParameters,
    HostedSearchResult,
    NativeReadTarget,
    TicketAskResult,
)
from app.services.agent_gateway.tool_check import DECISION_DENY, ToolDecision, record_denial
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.services.model_gateway.inbound.anthropic_stream import Observation
from app.services.model_gateway.inbound.codex_seat_observer import CodexSeatObserver
from app.services.model_gateway.inbound.seat_transcript import HOSTED_SEARCH_TOOL, SeatCallRecord
from app.services.model_gateway.inbound.seat_transcript import _write as write_seat_call
from app.services.model_gateway.inbound.transcript_tools import upsert_gateway_tool_calls
from app.services.model_gateway.inbound.turn_delta import newest_turn
from tests.agent_gateway_hook_support import confirm_hook_input
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.agent_gateway.test_agent_gateway_confirmation_security import _setup
from tests.test_workflow_run_octryx_decisions import CONFIRM, _terminal
from tests.typed_dict_support import shape_problems
from tests.workflow_run_runtime_evidence_support import ROOT, _device_session

pytestmark = pytest.mark.usefixtures("scripted_pool")

JUNIT = '<testsuite><testcase classname="tests.test_core" name="test_split"/></testsuite>'


async def _stored(db, session_id: str) -> list[ToolCall]:
    db.expire_all()
    return list((await db.execute(select(ToolCall).where(ToolCall.session_id == session_id))).scalars())


def _hook(tool: str, tool_use_id: str, tool_input: dict, **extra) -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_use_id": tool_use_id, "cwd": ROOT,
            "tool_input": tool_input, **extra}


def _turn(*uses: tuple[str, str, dict]) -> list[dict]:
    return [{"role": "user", "content": "go"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": use_id, "name": name, "input": tool_input}
                                              for use_id, name, tool_input in uses]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "ok",
                                          "is_error": False} for use_id, _, _ in uses]}]


async def test_hook_first_and_gateway_first_rows_store_the_gateway_tool_call_shape(db):
    gateway, _key = await _device_session(db, await admin_user(db), await seed_workspace(db))
    gateway.metadata_ = {**gateway.metadata_, "engine": "codex"}
    read_id, shell_id, test_id = (f"toolu_{uuid.uuid4().hex[:12]}" for _ in range(3))
    await record_tool_execution(db, session=gateway, hook_input=_hook(
        "Read", read_id, {"file_path": f"{ROOT}/textkit/core.py"}, agent_id="agent_1"))
    await record_tool_execution(db, session=gateway, hook_input=_hook(
        "Bash", shell_id, {"command": "cat textkit/core.py"}))
    await upsert_gateway_tool_calls(db, gateway.id, newest_turn(_turn(
        (read_id, "Read", {"file_path": f"{ROOT}/textkit/core.py"}), (shell_id, "Bash", {"command": "cat x"}),
        (test_id, "Bash", {"command": "pytest -q"}))))
    await db.flush()
    await record_tool_execution(db, session=gateway, hook_input=_hook(
        "Bash", test_id, {"command": "pytest -q"},
        workflow_run_facts={"test_report": {"junit_xml": JUNIT, "path": "report.xml", "files": ["tests/test_core.py"]}}))
    await record_tool_execution(db, session=gateway, hook_input=_hook(
        "Bash", f"exec-{uuid.uuid4()}", {"command": "cat textkit/core.py"}))
    await db.commit()
    rows = await _stored(db, gateway.id)
    assert len(rows) == 4
    for row in rows:
        assert shape_problems(row.parameters, GatewayToolCallParameters, row.tool_name) == []
        assert shape_problems(row.result, GatewayToolCallResult | None, row.tool_name) == []
    stored_keys = set().union(*(row.parameters for row in rows))
    assert stored_keys == set(GatewayToolCallParameters.__annotations__)


async def test_a_recorded_denial_stores_the_hook_denial_shape(db):
    gateway, _key = await _device_session(db, await admin_user(db), await seed_workspace(db))
    remedy = {"setting": "device_runs.tool_defaults.allowed_tools", "value": ["Fetch"], "tool": "Fetch"}
    await record_denial(db, session=gateway, hook_input={"tool_name": "Bash", "tool_use_id": "toolu_1",
                                                         "tool_input": {"command": "git push", "timeout": 5}},
                        decision=ToolDecision(DECISION_DENY, "denied", "tool_rule_denied", "no-push", "No."))
    await record_denial(db, session=gateway, hook_input={"tool_name": "Fetch", "tool_input": {"url": "x"}},
                        decision=ToolDecision(DECISION_DENY, "denied", "tool_not_classified", None, "No.",
                                              remedy=remedy))
    await db.commit()
    for row in await _stored(db, gateway.id):
        assert shape_problems(row.parameters, HookDenialParameters, row.tool_name) == []
        assert shape_problems(row.result, HookDenialResult, row.tool_name) == []


async def test_a_confirmation_ask_stores_its_ticket_shape(db):
    from app.services.agent_gateway.confirmation import ask_for_confirmation

    _, _, gateway, session_key, _, approval_id, key = await _setup(db)
    hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    assert (await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input))[
        "decision"] == "ask"
    await db.commit()
    [row] = await _stored(db, gateway.id)
    assert shape_problems(row.parameters, ConfirmationTicketParameters, "parameters") == []
    assert shape_problems(row.result, TicketAskResult, "result") == []


async def test_a_decision_ask_and_its_refusal_store_their_shapes(db):
    terminal = await _terminal(db, CONFIRM)
    stale = await terminal.pre_tool_use({"action": "confirm", "payload_hash": "sha256:" + "0" * 64})
    assert stale["decision"] == "deny"
    payload_hash = terminal.run.node_state["waiting"]["payload_hash"]
    asked = await terminal.pre_tool_use({"action": "confirm", "payload_hash": payload_hash}, tool_use_id="toolu_2")
    assert asked["decision"] == "ask"
    await db.commit()
    rows = await _stored(db, terminal.gateway.id)
    [ask] = [row for row in rows if row.status == "confirmation_asked"]
    [denial] = [row for row in rows if row.status == contract.TOOL_CALL_STATUS_DENIED]
    assert ask.tool_name == WORKFLOW_DECIDE_HOOK_TOOL
    assert shape_problems(ask.parameters, DecisionTicketParameters, "parameters") == []
    assert shape_problems(ask.result, TicketAskResult, "result") == []
    assert shape_problems(denial.parameters, HookDenialParameters, "parameters") == []
    assert shape_problems(denial.result, HookDenialResult, "result") == []


async def test_an_observed_hosted_search_is_stored_in_the_hosted_search_shape(db):
    admin = await admin_user(db)
    gateway, _key = await _device_session(db, admin, await seed_workspace(db))
    observation = Observation()
    observer = CodexSeatObserver(observation)
    for item in ({"type": "web_search_call", "id": "ws_1", "status": "completed",
                  "action": {"type": "search", "query": "roast rest days"}},
                 {"type": "web_search_call"}):
        event = {"type": "response.output_item.done", "item": item}
        observer.feed(f"event: response.output_item.done\ndata: {json.dumps(event)}\n\n".encode())
    observer.finish()
    await write_seat_call(db, SeatCallRecord(
        session_id=gateway.id, user_id=admin.id, model="gpt-6.1-sol",
        body={"messages": [{"role": "user", "content": "search"}]}, observation=observation,
        upstream_request_id="req", duration_ms=10, status_code=200))
    await db.commit()
    rows = [row for row in await _stored(db, gateway.id) if row.tool_name == HOSTED_SEARCH_TOOL]
    assert len(rows) == 2
    for row in rows:
        assert shape_problems(row.parameters, HostedSearchParameters, "parameters") == []
        assert shape_problems(row.result, HostedSearchResult, "result") == []


def test_the_literal_vocabularies_are_the_constants_the_code_compares_with():
    assert get_args(GatewaySource) == (contract.TOOL_CALL_SOURCE_GATEWAY,)
    assert get_args(HookSource) == (contract.TOOL_CALL_SOURCE_HOOK,)
    assert set(get_args(ExecutionOutcome)) == {contract.EXECUTION_OUTCOME_SUCCEEDED, contract.EXECUTION_OUTCOME_FAILED}
    assert set(get_args(NativeReadTarget.__annotations__["tool"])) == set(NATIVE_READ_EVIDENCE)
    assert contract.TOOL_CALL_EXECUTED_KEY in GatewayToolCallParameters.__annotations__
