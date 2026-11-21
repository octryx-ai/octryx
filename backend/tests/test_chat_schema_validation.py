"""Tests for schema boundary validation and send endpoint behavior."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.agent.core.runtime.standard_loop as standard_loop_module
import app.agent.engine as engine_module
from app.models import Message, Session, SystemConfig, User
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
async def test_chat_send_requires_non_empty_prompt_at_schema_boundary(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    resp = await client.post("/admin/chat/api/send", json={"prompt": ""})

    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"] == "Validation failed"
    assert payload["status_code"] == 422
    assert payload["request_id"]
    assert payload["validation_errors"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_propagates_request_id_into_turn_trace(client, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "Request ID propagation verified.",
                "model": "claude-haiku-4.5",
                "tool_calls": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
            runtimes[0],
            [],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(standard_loop_module, "_plan_coding_preflight_tool_calls", lambda **kwargs: [])

    send_resp = await client.post(
        "/admin/chat/api/send",
        headers={"X-Request-ID": "req-chat-123"},
        json={"prompt": "Give me a short answer."},
    )
    assert send_resp.status_code == 200
    assert send_resp.headers["X-Request-ID"] == "req-chat-123"
    session_id = send_resp.json()["selectedSession"]["id"]

    final_payload = send_resp.json()
    for _ in range(40):
        await asyncio.sleep(0.05)
        bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert bootstrap_resp.status_code == 200
        final_payload = bootstrap_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assistant_messages = [item for item in final_payload["selectedMessages"] if item["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1]["turnTrace"] is None
    trace_id = assistant_messages[-1]["turnTraceId"]
    assert trace_id
    trace_resp = await client.get(f"/admin/chat/api/turn-traces/{trace_id}")
    assert trace_resp.status_code == 200
    assert trace_resp.json()["contextSnapshot"]["request_id"] == "req-chat-123"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_respects_trace_string_limit_from_system_config(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    db.add(
        SystemConfig(
            key="agent.trace_max_string",
            value="80",
            description="test trace string limit",
        )
    )
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "A" * 200,
                "model": "claude-haiku-4.5",
                "tool_calls": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
            runtimes[0],
            [],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={"prompt": "Give me a short answer."},
    )
    assert send_resp.status_code == 200
    session_id = send_resp.json()["selectedSession"]["id"]

    final_payload = send_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert bootstrap_resp.status_code == 200
        final_payload = bootstrap_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assistant_messages = [item for item in final_payload["selectedMessages"] if item["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1]["turnTrace"] is None
    trace_id = assistant_messages[-1]["turnTraceId"]
    assert trace_id
    trace_resp = await client.get(f"/admin/chat/api/turn-traces/{trace_id}")
    assert trace_resp.status_code == 200
    trace_content = trace_resp.json()["rawOutput"]["content"]
    assert trace_content.endswith("\n...[truncated]")
    assert len(trace_content) < 120


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_message_feedback_requires_supported_rating_at_schema_boundary(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="chat",
        status="active",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="hello",
    )
    db.add(message)
    await db.commit()

    resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/messages/{message.id}/feedback",
        json={"rating": 0, "comment": "invalid"},
    )

    assert resp.status_code == 422
