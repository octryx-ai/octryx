"""Agent loop guards: message budget trimming, transitional replies, step tool lists and stopping on pending approval."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    _is_transitional_assistant_response,
    _trim_messages_to_budget,
    run_agent,
)
from app.models import AgentStep, Message, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def test_trim_messages_to_budget_drops_old_context_before_current_turn():
    messages = [
        {"role": "system", "content": "S" * 5000},
        {"role": "user", "content": "old-1 " * 800},
        {"role": "assistant", "content": "old-2 " * 800},
        {"role": "user", "content": "current request"},
    ]

    trimmed = _trim_messages_to_budget(messages, 1200)

    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["content"] == "current request"
    assert len(trimmed) < len(messages)


def test_trim_messages_to_budget_preserves_assistant_tool_and_tool_result_pair():
    messages = [
        {"role": "system", "content": "S" * 5000},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tool-1", "function": {"name": "bash", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tool-1", "content": '{"ok": true}'},
        {"role": "user", "content": "current request"},
    ]

    trimmed = _trim_messages_to_budget(messages, 1200)

    roles = [item["role"] for item in trimmed]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert roles[1:3] == ["assistant", "tool"]


def test_transitional_assistant_response_detects_retry_language():
    assert _is_transitional_assistant_response(
        "Let me try once more with a higher timeout:",
        None,
        True,
    )


def test_agent_step_allowed_tools_returns_empty_list_for_invalid_json_shapes():
    step = AgentStep(name="Test", allowed_tools_json='{"not":"a-list"}')
    assert step.allowed_tools == []

    step.allowed_tools_json = "not-json"
    assert step.allowed_tools == []


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_stops_after_pending_approval_tool_result(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.flush()

    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Run python3 manage.py migrate",
    )
    db.add(user_message)
    session.metadata_ = {**UNDECLARED_READ_ONLY_RUN, "current_turn_user_message_id": user_message.id}
    await db.commit()

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        assert tool_name == "run_cli_command"
        assert tool_args["command"] == "python3 manage.py migrate"
        return {
            "error": "Execution blocked by policy: Diagnosis mode requires approval.",
            "tool_name": "run_cli_command",
            "command": "python3 manage.py migrate",
            "exec_policy_action": "review",
            "exec_policy_reason": "Diagnosis mode requires approval.",
            "exec_policy_risk": "medium",
            "approval_required": True,
            "approval_status": "pending",
        }

    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    # The chat set's command tool is the policy-governed `run_cli_command`; the model calls it and
    # the pending approval stops the turn (No prompt regex synthesizes a command call).
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "eu.anthropic.claude-sonnet-4-5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        assert "run_cli_command" in {tool["function"]["name"] for tool in tools}
        response = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-migrate",
                    "function": {"name": "run_cli_command", "arguments": '{"command": "python3 manage.py migrate"}'},
                }
            ],
            "model": runtimes[0]["model"],
            "usage": {},
        }
        return response, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Run python3 manage.py migrate",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        events.append(event)

    assert any(event.role == "tool" for event in events)
    assert not any(event.role == "assistant" and event.content for event in events)
