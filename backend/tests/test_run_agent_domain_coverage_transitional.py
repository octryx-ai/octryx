"""The agent never finalizes on a transitional phrase and stops early on repeated transitional responses."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Message, Project, Session, TurnTrace, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_does_not_finalize_on_transitional_search_phrase(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    # Explicit-first routing no longer grants knowledge tools from
    # question-shaped text; task context is the explicit session signal that
    # keeps the full working context (and tools) for this guard scenario.
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="running",
        metadata_={**UNDECLARED_READ_ONLY_RUN, "task_id": f"task-{uuid.uuid4()}"},
    )
    db.add(session)
    await db.commit()

    response_queue = [
        {
            "content": "I can see that Acme Orders is documented in the Knowledge Map. Let me search for specific information about the health check:",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-knowledge",
                    "function": {
                        "name": "list_project_knowledge",
                        "arguments": '{"query": "health check", "limit": 5}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
        },
        {
            "content": "Health check in Acme Orders is documented via the plugin and exposes component checks for database, DynamoDB, metrics, and Swagger endpoints.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 18, "completion_tokens": 6, "total_tokens": 24},
        },
    ]

    executed_tools = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return {
            "project_name": "acme-orders",
            "results": [
                {
                    "title": "HealthCheck Plugin",
                    "summary": "Health check plugin with database, DynamoDB, metrics, and Swagger probes.",
                }
            ],
        }

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="wie funktioniert der health check in acme-orders genau",
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        db=db,
    ):
        events.append(event)

    assert executed_tools == ["list_project_knowledge"]
    assert events[-1].content.startswith("Health check in Acme Orders is documented")

    assistant_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id, Message.role == "assistant")
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(assistant_messages) == 2


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_stops_early_on_repeated_transitional_responses(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    response_queue = [
        {
            "content": "Let me inspect the existing files first:",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        },
        {
            "content": "Now let me inspect the existing files:",
            "tool_calls": None,
            "model": "Claude Haiku 4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        },
    ]

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Implement the requested code change now.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        db=db,
    ):
        events.append(event)

    assert events
    assert "kept producing transition text" in events[-1].content or "kept producing text" in events[-1].content

    traces = (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert any((trace.raw_output or {}).get("suppressed_as_transitional") for trace in traces)
    assert any((trace.raw_output or {}).get("stalled_on_transitional_loop") for trace in traces)
