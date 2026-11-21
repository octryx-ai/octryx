"""The selected agent's checked reply contract at the runtime boundary.

The real ``run_agent`` loop with a scripted provider (``test_agent_tool_surface_runtime``): a
``json_object`` agent's final reply is checked once after the answer-evidence guard. A satisfied
reply finishes unchanged; a violated one is delivered exactly as the model wrote it and the turn
reads ``stopped`` with the validator's closed code. Nothing is retried, stripped or repaired.
Free-text and legacy agents are unchanged. An invalid contract or a workflow turn is held before
any model call.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.core.prompts.agent_blueprint import REPLY_FORMAT_HEADING, agent_reply_format_section
from app.agent.harness.activation import (
    HARNESS_RUNTIME_NATIVE,
    REASON_FLAG_UNRECOGNIZED,
    ConfiguredHarnessRuntime,
    resolve_harness_activation,
)
from app.agent.loops.response._loop_reply_contract import (
    REASON_PATH_UNSUPPORTED,
    apply_reply_contract_admission_to_profile,
    evaluate_reply_contract_admission,
    handle_reply_contract_check,
)
from app.models import FlowNodeRun, Message, Session, User
from app.services.session.turn_execution_snapshot import AGENT_REPLY_CONTRACT_KEY
from app.services.session.turn_execution_summary import runtime_outcome_from_trace
from app.tools.context import ToolContext
from app.tools.sub_agent import SpawnSubAgentTool
from tests.agent_reply_contract_runtime_support import CONTRACT, FENCED, VALID, _checked_agent, _final_trace, _summary
from tests.agent_tool_surface_runtime_support import _agent, _run, _Script, _session

MISTYPED = '{"total": "43"}'


@pytest.mark.asyncio
async def test_a_satisfied_reply_finishes_unchanged_and_the_prompt_states_the_format(db, monkeypatch):
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": VALID, "tool_calls": None}])

    contents = await _run(db, admin, session, agent_definition=_checked_agent())

    assert contents == [VALID]
    assert len(script.calls) == 1
    assert any(REPLY_FORMAT_HEADING in text and '"total": <integer>' in text for text in script.calls[0]["system"])
    trace = await _final_trace(db, session.id)
    assert runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output) == "finished"
    summary = await _summary(db, trace)
    assert summary["state"] == "finished_unverified"
    assert summary["reply_contract"] == {"kind": "json_object", "status": "satisfied", "reason": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "reason"), [(FENCED, "agent_reply_not_json"), (MISTYPED, "agent_reply_schema_mismatch")])
async def test_a_violated_reply_is_delivered_exactly_and_the_turn_reads_stopped(db, monkeypatch, reply, reason):
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": reply, "tool_calls": None}])

    contents = await _run(db, admin, session, agent_definition=_checked_agent())

    # One model call: no reminder, no hidden retry; the exact reply reaches the user.
    assert len(script.calls) == 1
    assert contents == [reply]
    trace = await _final_trace(db, session.id)
    delivered = await db.get(Message, trace.message_id)
    assert delivered.content == reply and trace.raw_output["content"] == reply
    assert runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output) == "stopped"
    summary = await _summary(db, trace)
    assert summary["state"] == "stopped"
    assert summary["state_reason"]["code"] == f"runtime_stopped_{reason}"
    assert summary["reply_contract"] == {"kind": "json_object", "status": "violated", "reason": reason}
    assert reply not in str(summary["state_reason"]) and reply not in str(summary["reply_contract"])


@pytest.mark.asyncio
@pytest.mark.parametrize("contract", [None, {"kind": "text"}])
async def test_free_text_and_legacy_agents_are_unchanged(db, monkeypatch, contract):
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": FENCED, "tool_calls": None}])
    agent = _agent(None) if contract is None else _checked_agent(contract)

    contents = await _run(db, admin, session, agent_definition=agent)

    assert contents == [FENCED] and len(script.calls) == 1
    assert not any(REPLY_FORMAT_HEADING in text for text in script.calls[0]["system"])
    trace = await _final_trace(db, session.id)
    assert AGENT_REPLY_CONTRACT_KEY not in trace.context_snapshot_json
    assert runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output) == "finished"
    assert (await _summary(db, trace))["reply_contract"] is None


@pytest.mark.asyncio
async def test_an_invalid_stored_contract_holds_the_turn_before_any_model_call(db, monkeypatch):
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": VALID, "tool_calls": None}])
    corrupt = {"kind": "json_object", "schema": {"type": "object", "properties": {}, "required": []}}

    await _run(db, admin, session, agent_definition=_checked_agent(corrupt))

    assert script.calls == []
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert (profile["status"], profile["reason_code"]) == ("needs_configuration", "agent_reply_contract_invalid")
    assert (await _summary(db, await _final_trace(db, session.id)))["state"] == "needs_configuration"


def test_admission_holds_workflow_and_coordinator_turns_and_keeps_a_selected_agent_allowed():
    agent = _checked_agent()
    allowed = {"status": "allowed", "execution_strategy": "specialist", "workflow_id": None}
    assert evaluate_reply_contract_admission(agent, allowed).allowed is True
    assert evaluate_reply_contract_admission(_agent(None), allowed) is None
    for profile, workflow_id in (({**allowed}, "code_review"), ({**allowed, "execution_strategy": "coordinator"}, None)):
        admission = evaluate_reply_contract_admission(agent, profile, workflow_id=workflow_id)
        assert (admission.allowed, admission.reason_code) == (False, REASON_PATH_UNSUPPORTED)
        held = apply_reply_contract_admission_to_profile(profile, admission)
        assert (held["status"], held["reason_code"]) == ("needs_configuration", REASON_PATH_UNSUPPORTED)
    # An already blocked profile keeps its own, earlier decision.
    blocked = {**allowed, "status": "denied", "reason_code": "earlier"}
    admission = evaluate_reply_contract_admission(agent, blocked, workflow_id="code_review")
    assert apply_reply_contract_admission_to_profile(blocked, admission)["reason_code"] == "earlier"


@pytest.mark.asyncio
async def test_tool_call_replies_and_non_final_steps_are_never_checked_and_drop_an_earlier_result():
    calls: list[dict] = []

    async def persist(**kwargs):
        calls.append(kwargs)

    context = {AGENT_REPLY_CONTRACT_KEY: {"kind": "json_object", "status": "satisfied", "reason": None}}
    common = {
        "db": None, "session_id": "s", "runtime": {"provider_name": "bedrock"}, "response": {}, "request_messages": [],
        "context_snapshot": context, "runtime_attempts": [], "runtime_settings": {}, "usage_model": "m",
        "content": "Let me check the numbers first.", "agent_definition": _checked_agent(),
        "persist_traced_assistant_message": persist,
    }
    tool_call = [{"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}]
    assert await handle_reply_contract_check(**common, tool_calls=tool_call, has_followup_steps=False) is None
    assert AGENT_REPLY_CONTRACT_KEY not in context
    assert await handle_reply_contract_check(**common, tool_calls=None, has_followup_steps=True) is None
    assert AGENT_REPLY_CONTRACT_KEY not in context and calls == []


def test_the_prompt_section_renders_only_for_a_valid_checked_contract():
    assert REPLY_FORMAT_HEADING in agent_reply_format_section(_checked_agent())
    assert agent_reply_format_section(_agent(None)) == ""
    assert agent_reply_format_section(_checked_agent({"kind": "text"})) == ""
    assert agent_reply_format_section(_checked_agent({"kind": "json_object"})) == ""


def test_the_harness_leaves_a_checked_agent_to_the_native_loop():
    activation = resolve_harness_activation(
        configured=ConfiguredHarnessRuntime(value="unrecognized-runtime", readable=True),
        execution_profile={"execution_strategy": "direct"},
        agent_definition=_checked_agent(),
    )
    assert (activation.runtime, activation.reason) == (HARNESS_RUNTIME_NATIVE, REASON_FLAG_UNRECOGNIZED)


@pytest.mark.asyncio
async def test_spawned_children_answer_their_parent_without_the_reply_contract(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent = Session(id=str(uuid.uuid4()), user_id=admin.id, status="running", metadata_={})
    db.add(parent)
    await db.commit()
    launches: list[dict] = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch)
    parent_definition = {**_checked_agent(), "agentType": "diagnosis"}
    await SpawnSubAgentTool().execute(
        {"sub_tasks": ["Inspect service alpha"]},
        ToolContext(
            user_id=admin.id, project_ids=[], roles=["admin"], session_id=parent.id, project_config={}, db=db,
            system_context={}, capability_type="diagnosis", agent_mode_key="diagnosis",
            turn_context_snapshot={}, agent_definition=parent_definition,
        ),
    )

    child_definition = launches[0]["agent_definition"]
    assert "replyContract" not in child_definition and child_definition["name"] == parent_definition["name"]
    assert "replyContract" in parent_definition, "the parent's own payload is not mutated"


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "completed"), [(VALID, True), (FENCED, False)])
async def test_a_flow_agent_node_passes_only_a_satisfied_reply_downstream(db, monkeypatch, answer, completed):
    """A flow node runs its selected agent at depth 1: the check still applies and a stop fails the node."""
    from app.services.flow_orchestration.runner import execute_flow_version
    from tests.flow_agent_step_support import _admin_and_project, _flow, _node_run, _provider_double
    from tests.flow_agent_step_support import _agent as _flow_agent

    admin, project = await _admin_and_project(db)
    agent = await _flow_agent(db, admin.id, project_id=project.id)
    agent.reply_contract_json = json.dumps(CONTRACT)
    await db.flush()
    calls = _provider_double(monkeypatch, answer=answer)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum the numbers."})

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "31, 8, 4"}
    )

    assert len(calls) == 1
    node = await _node_run(db, run, "summarise")
    downstream = (
        await db.execute(select(FlowNodeRun).where(FlowNodeRun.orchestrator_run_id == run.id, FlowNodeRun.node_id == "end"))
    ).scalar_one_or_none()
    if completed:
        assert run.status == "completed" and node.output_json["result"] == VALID
        assert downstream is not None
    else:
        assert run.status == "failed" and node.error.startswith("agent_turn_stopped")
        assert downstream is None


# --- delegated runtimes and edge cases -------------------------------------------------


@pytest.mark.asyncio
async def test_a_checked_agent_with_a_selected_workflow_is_refused_in_a_real_turn(db, monkeypatch):
    from tests.test_zero_tool_turn import _workspace_with_selected_definition

    admin, _project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    script = _Script(monkeypatch, [])

    await _run(db, admin, session, agent_definition={**_checked_agent(), "toolSurface": "governed"}, message=message)

    assert script.calls == [], "a workflow turn never runs a checked agent unchecked"
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert (profile["status"], profile["reason_code"]) == ("needs_configuration", "agent_reply_contract_path_unsupported")
