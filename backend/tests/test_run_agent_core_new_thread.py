"""Tests for core run_agent: creates thread+trace, no duplicate user message, minimal prompt, cached response, and prompt injection."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    AgentEvent,
    run_agent,
)
from app.models import LLMProvider, Message, Project, Session, ToolCall, TurnTrace, User
from app.services.control_plane_service import upsert_runtime_target
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


async def _seed_openrouter_target(db):
    """A global OpenRouter provider with a primary runtime target; return the target id."""
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    target = await upsert_runtime_target(
        db,
        provider=provider,
        model_id="stepfun/step-3.5-flash:free",
        make_primary=True,
    )
    await db.commit()
    target_id = target.id
    return target_id


async def _persist_checked_turn(db, session_id):
    """Store the assistant message, its Bitbucket tool call and the turn trace the fake agent run produces."""
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content="Checked Bitbucket and Confluence.",
        tool_calls=[
            {
                "id": "tool-1",
                "function": {"name": "list_bitbucket_repositories", "arguments": "{}"},
            }
        ],
        model="stepfun/step-3.5-flash:free",
        tokens_in=123,
        tokens_out=45,
    )
    db.add(assistant_message)
    await db.flush()
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session_id,
            message_id=assistant_message.id,
            tool_name="list_bitbucket_repositories",
            parameters={},
            result={"repositories": [{"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin"}]},
            status="success",
            duration_ms=37,
        )
    )
    db.add(
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=session_id,
            message_id=assistant_message.id,
            provider="openrouter",
            model="stepfun/step-3.5-flash:free",
            input_messages_json=[
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "Check configured systems"},
            ],
            context_snapshot_json={"summary": "Demo context"},
            tool_trace_json=[
                {
                    "tool_name": "list_bitbucket_repositories",
                    "result": {"repositories": [{"repo_slug": "acme-orders-catalog-plugin"}]},
                }
            ],
            raw_output={"content": "Checked Bitbucket and Confluence."},
            usage_json={"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
        )
    )
    await db.commit()
    return assistant_message


def _make_fake_run_agent(observed):
    async def fake_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        agent_type,
        db,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        run_origin=None,
    ):
        observed["runtime_target_id"] = runtime_target_id
        observed["thinking_level"] = thinking_level
        observed["agent_definition"] = agent_definition
        await asyncio.sleep(0.05)
        assistant_message = await _persist_checked_turn(db, session_id)
        yield AgentEvent(role="tool", tool_calls=assistant_message.tool_calls, tool_results=[])
        yield AgentEvent(role="assistant", content="Checked Bitbucket and Confluence.")

    return fake_run_agent


def _assert_running_send_payload(payload, target_id):
    assert payload["selectedSession"] is not None
    assert payload["selectedSession"]["runtimeTargetId"] == target_id
    # Runtime S3 / D14: the label is the model's catalog display name, without the provider.
    assert payload["selectedSession"]["runtimeLabel"] == "stepfun/step-3.5-flash:free"
    assert payload["selectedThinkingLevel"] == "deep"
    assert payload["selectedSession"]["status"] == "running"
    assert payload["selectedSessionIsRunning"] is True
    assert payload["selectedMessages"][-1]["content"] == "Check configured systems"


async def _poll_until_idle(client, payload, session_id):
    final_payload = payload
    for _ in range(100):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break
    return final_payload


def _assert_completed_thread(final_payload, session_id):
    assert final_payload["selectedSessionIsRunning"] is False
    assert final_payload["selectedSession"]["status"] == "active"
    assert final_payload["selectedSession"]["runStatus"] == "completed"
    assert final_payload["selectedSession"]["runCompletionReason"] == "completed"
    assert final_payload["selectedMessages"][-1]["content"] == "Checked Bitbucket and Confluence."
    assert final_payload["selectedMessages"][-1]["runtimeLabel"] == "OpenRouter / stepfun/step-3.5-flash:free"
    assert final_payload["selectedMessages"][-1]["turnTrace"] is None
    assert final_payload["traceEvents"][0]["toolName"] == "list_bitbucket_repositories"
    selected_row = next(
        row for group in final_payload["activeThreadGroups"] for row in group["sessions"] if row["id"] == session_id
    )
    assert selected_row["status"] == "active"
    assert selected_row["runStatus"] == "completed"
    assert selected_row["runCompletionReason"] == "completed"
    assert final_payload["traceEvents"][0]["result"]["repositories"][0]["repo_slug"] == "acme-orders-catalog-plugin"
    assert final_payload["selectedThreadStats"]["inputTokens"] == 123
    assert final_payload["selectedThreadStats"]["outputTokens"] == 45
    assert final_payload["selectedThreadStats"]["contextTokens"] == 168
    assert final_payload["selectedThreadStats"]["requestCount"] == 1


async def _assert_turn_trace(client, trace_id):
    trace_resp = await client.get(f"/admin/chat/api/turn-traces/{trace_id}")
    assert trace_resp.status_code == 200
    trace_payload = trace_resp.json()
    assert trace_payload["provider"] == "openrouter"
    assert trace_payload["model"] == "stepfun/step-3.5-flash:free"
    assert trace_payload["usage"]["prompt_tokens"] == 123


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_send_creates_thread_and_renders_trace(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    demo_project_id = demo_project.id
    target_id = await _seed_openrouter_target(db)

    observed = {}
    monkeypatch.setattr(turn_runner, "run_agent", _make_fake_run_agent(observed))

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Check configured systems",
            "project_id": demo_project_id,
            "runtime_target_id": target_id,
            "thinking_level": "deep",
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    _assert_running_send_payload(payload, target_id)

    session_id = payload["selectedSession"]["id"]
    final_payload = await _poll_until_idle(client, payload, session_id)
    _assert_completed_thread(final_payload, session_id)
    trace_id = final_payload["selectedMessages"][-1]["turnTraceId"]
    assert trace_id
    await _assert_turn_trace(client, trace_id)
    await db.rollback()
    session = (await db.execute(select(Session).order_by(Session.started_at.desc()))).scalars().first()
    assert session is not None
    assert session.project_id == demo_project_id
    assert observed["runtime_target_id"] == target_id
    assert observed["thinking_level"] == "deep"
    # A turn that names no agent runs as the platform Assistant.
    assert observed["agent_definition"]["name"] == "Assistant"
    assert (session.metadata_ or {}).get("runtime_target_id") == target_id
    assert (session.metadata_ or {}).get("thinking_level") == "deep"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_does_not_duplicate_current_user_message_in_new_thread(db, monkeypatch):
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
        content="ping",
    )
    db.add(user_message)
    session.metadata_ = {**UNDECLARED_READ_ONLY_RUN, "current_turn_user_message_id": user_message.id}
    await db.commit()

    captured = {}

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return (
            {
                "content": "Pong",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="ping",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        events.append(event)

    sent_user_messages = [
        msg for msg in captured["messages"] if msg.get("role") == "user" and msg.get("content") == "ping"
    ]
    assert len(sent_user_messages) == 1
    assert events[-1].content == "Pong"
