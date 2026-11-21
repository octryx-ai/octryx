"""Tests for run_agent domain coverage: knowledge lookup, repository sync, and noop detection."""


import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Message, Project, User
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from tests.phased_workflow_fixtures import phased_definition, publish_phased

QUESTION = "wie funktioniert der health check in acme-orders genau"


def _knowledge_search_responses() -> list[dict]:
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-search",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": '{"query": "acme-orders health check"}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
        },
        {
            "content": "The Acme Orders health check is implemented through the HealthCheck plugin and reports component status for the database, DynamoDB, metrics, and related endpoints.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
        },
    ]


def _healthcheck_evidence_result() -> dict:
    return {
        "state": "ok",
        "result_count": 1,
        "evidence": [
            {
                "source_title": "HealthCheck Plugin",
                "text": "HealthCheck plugin with database, DynamoDB, metrics, and endpoint probes.",
            }
        ],
    }


def _stub_knowledge_runtime(monkeypatch, response_queue: list[dict], executed_tools: list[str]) -> None:
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _healthcheck_evidence_result()

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)


@pytest.mark.asyncio
async def test_run_agent_answers_knowledge_question_from_planned_evidence(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    # Knowledge workflows run as a phase of a workflow run: the session follows the run's knowledge phase.
    key = await publish_phased(db, phased_definition())
    run = await start_run(db, user=admin, workflow_key=key, project_id=project.id)
    session = await new_bound_session(db, run, admin)
    # Persist the phase's resolution the way the turn preparation does.
    resolution = await run_turn_resolution(db, session, user_message=QUESTION)
    session.metadata_ = {**(session.metadata_ or {}), ROUTING_RESOLUTION_KEY: resolution}
    session.agent_type, session.status = "chat", "running"
    await db.commit()

    response_queue = _knowledge_search_responses()

    executed_tools = []
    _stub_knowledge_runtime(monkeypatch, response_queue, executed_tools)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message=QUESTION,
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        db=db,
    ):
        events.append(event)

    # The knowledge phase plans governed evidence only.
    assert set(executed_tools) == {"knowledge_search"}
    assert events[-1].content.startswith("The Acme Orders health check is implemented")

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
    assert assistant_messages[-1].content == (
        "The Acme Orders health check is implemented through the HealthCheck plugin and reports component status for "
        "the database, DynamoDB, metrics, and related endpoints."
    )
    assert any(msg.tool_calls is not None for msg in assistant_messages)

