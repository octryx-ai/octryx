"""Dispatching tool calls for a turn: malformed arguments and names, runtime tool events and the selected tool plan."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.core.turn.tool_call_recording as tool_call_recording_module
import app.agent.core.turn.turn_tools as turn_tools_module
from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import ToolCall
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_handles_malformed_tool_arguments(db):
    turn_diff_tracker = TurnDiffTracker()
    seen: dict[str, Any] = {}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        seen["tool_name"] = tool_name
        seen["tool_args"] = tool_args
        return {"status": "ok"}

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-1",
            "function": {
                "name": "todo_read",
                "arguments": "{definitely-not-json",
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    assert seen["tool_name"] == "todo_read"
    assert seen["tool_args"] == {}
    assert executed.tool_result["result"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_publishes_runtime_tool_events(db, monkeypatch):
    turn_diff_tracker = TurnDiffTracker()
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def fake_publish_begin(**kwargs):
        emitted.append(("begin", kwargs))

    async def fake_publish_end(**kwargs):
        emitted.append(("end", kwargs))

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        return {
            "status": "ok",
            "query": tool_args["query"],
            "execution_event": {
                "kind": "shell",
                "tool_name": tool_name,
                "cwd": "/workspace/repo",
                "status": "succeeded",
                "exit_code": 0,
                "duration_ms": 12,
                "stdout_chars": 2,
                "stderr_chars": 0,
                "stdout_truncated": False,
                "stderr_truncated": False,
            },
        }

    monkeypatch.setattr(turn_tools_module, "publish_tool_call_begin", fake_publish_begin)
    monkeypatch.setattr(tool_call_recording_module, "publish_tool_call_end", fake_publish_end)

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-runtime-events",
            "function": {
                "name": "todo_read",
                "arguments": json.dumps({"query": "Who is Alice Example?"}),
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            request_id="req-runtime-events",
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    assert [event_type for event_type, _payload in emitted] == ["begin", "end"]
    begin_payload = emitted[0][1]
    end_payload = emitted[1][1]
    assert begin_payload["session_id"] == end_payload["session_id"]
    assert begin_payload["turn_id"] == "req-runtime-events"
    assert begin_payload["tool_call_id"] == "call-runtime-events"
    assert begin_payload["tool_name"] == "todo_read"
    assert begin_payload["parameters"] == {"query": "Who is Alice Example?"}
    assert end_payload["tool_call_id"] == "call-runtime-events"
    assert end_payload["tool_name"] == "todo_read"
    assert end_payload["status"] == "success"
    assert end_payload["artifact_id"] == executed.tool_result["artifact_id"]
    assert end_payload["result_preview"]["status"] == "ok"
    assert end_payload["result_preview"]["query"] == "Who is Alice Example?"
    assert end_payload["result_preview"]["execution_event"]["kind"] == "shell"
    persisted = (
        await db.execute(select(ToolCall).where(ToolCall.id == executed.tool_result["artifact_id"]))
    ).scalar_one()
    assert persisted.result["execution_event"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_sanitizes_malformed_tool_name(db):
    turn_diff_tracker = TurnDiffTracker()
    seen: dict[str, Any] = {}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        seen["tool_name"] = tool_name
        return {"status": "ok"}

    tool_call = {
        "id": "call-xml",
        "function": {
            "name": 'list_project_knowledge</parameter>\n<parameter name="query"',
            "arguments": "{}",
        },
    }

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call=tool_call,
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="knowledge",
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names={"list_project_knowledge", "get_confluence_page"},
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={},
    )

    assert seen["tool_name"] == "list_project_knowledge"
    assert tool_call["function"]["name"] == "list_project_knowledge"
    assert executed.tool_result["result"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_enforces_selected_tool_plan(db):
    turn_diff_tracker = TurnDiffTracker()
    seen: dict[str, Any] = {"called": False}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        seen["called"] = True
        return {"status": "ok"}

    executed = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=str(uuid.uuid4()),
        tool_call={
            "id": "call-denied",
            "function": {
                "name": "aws_topology_snapshot",
                "arguments": "{}",
            },
        },
        tool_context=ToolContext(
            user_id="u1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
            capability_type="diagnosis",
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names={"aws_topology_snapshot", "knowledge_search", "knowledge_get"},
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=turn_diff_tracker,
        context_snapshot={
            "tool_execution_control_contract": {
                "contract_kind": "tool_execution_control",
                "intent_class": "knowledge_question",
                "selected_tools": ["knowledge_search", "knowledge_get"],
                "budget": {"max_tool_calls": 4},
                "enforcement": {"enabled": True, "max_tool_calls": 4},
            }
        },
    )

    assert seen["called"] is False
    assert executed.tool_result["result"]["code"] == "tool_execution_control_denied"
    assert executed.tool_result["result"]["reason"] == "tool_not_in_execution_plan"
