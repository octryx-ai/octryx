import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Message, Session, TurnTrace, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
async def test_run_agent_attaches_token_pressure_and_normalizes_pre_dispatch_messages(db, monkeypatch):
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
    db.add_all(
        [
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="assistant",
                content="I started an earlier tool call.",
                tool_calls=[
                    {"id": "call-keep", "function": {"name": "todo_read", "arguments": "{}"}},
                    {"id": "call-drop", "function": {"name": "todo_read", "arguments": "{}"}},
                ],
            ),
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="tool",
                content='{"ok": false}',
            ),
        ]
    )
    await db.commit()

    observed_request_messages: list[list[dict[str, object]]] = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        observed_request_messages.append(messages)
        return (
            {
                "content": "Normalized and dispatched successfully.",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Continue the investigation.",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        continue

    assert observed_request_messages
    dispatched_messages = observed_request_messages[-1]
    assert not any(message.get("role") == "tool" for message in dispatched_messages)
    assert not any(list(message.get("tool_calls") or []) for message in dispatched_messages)

    trace_query = select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at.desc())
    trace = (await db.execute(trace_query)).scalars().first()
    assert trace is not None
    attempts = trace.raw_output.get("runtime_attempts") or []
    assert attempts
    token_pressure = attempts[-1].get("token_pressure") or {}
    assert token_pressure.get("kind") == "token_pressure_breakdown"
    assert "history_invariant" in token_pressure
    assert token_pressure.get("compaction", {}).get("pre_dispatch_guard") is True
