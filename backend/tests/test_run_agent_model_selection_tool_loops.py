"""Tests for run_agent model selection: self-review appending, repeated tool loops, stagnation, and domain coverage skip."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _document_updater_definition() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Document Updater",
        "steps": [
            {
                "name": "Confluence aktualisieren",
                "stepType": "change",
                "instructions": "Arbeite auf bereits identifizierten Seiten.",
                "successCriteria": "Die betroffenen Seiten wurden aktualisiert oder es gibt eine klare Begruendung, warum keine Aenderung noetig war.",
                "allowedTools": [
                    "list_confluence_pages",
                    "get_confluence_page",
                    "update_confluence_page",
                    "create_confluence_page",
                ],
                "isEnabled": True,
            }
        ],
    }


def _tool_call_response(call_id: str, name: str, arguments: str) -> dict:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ],
        "model": "claude-haiku-4.5",
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def _looping_responses() -> list[dict]:
    """Four tool calls that alternate between listing and reading the same Confluence page."""
    return [
        _tool_call_response("call-1", "list_confluence_pages", '{"space_key": "INFRA", "limit": 5}'),
        _tool_call_response("call-2", "get_confluence_page", '{"page_id": "100001"}'),
        _tool_call_response("call-3", "list_confluence_pages", '{"space_key": "INFRA", "limit": 5}'),
        _tool_call_response("call-4", "get_confluence_page", '{"page_id": "100001"}'),
    ]


def _stub_engine(monkeypatch, response_queue: list[dict], observed_request_messages: list) -> None:
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        observed_request_messages.append(messages)
        if response_queue:
            return response_queue.pop(0), runtimes[0]
        return (
            {
                "content": "The documentation impact is limited to the report-builder operational Confluence page.",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            },
            runtimes[0],
        )

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        if tool_name == "list_confluence_pages":
            return {"pages": [{"id": "100001", "title": "Report Builder guide"}]}
        return {"id": "100001", "title": "Report Builder guide", "content": "<p>Report Builder docs</p>"}

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)
    monkeypatch.setattr(engine_module, "_max_iterations_for_agent_step", lambda step: 2)


@pytest.mark.asyncio
async def test_run_agent_stops_after_repeated_final_step_tool_loops(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    agent_definition = _document_updater_definition()

    response_queue = _looping_responses()
    observed_request_messages: list[list[dict[str, str]]] = []
    _stub_engine(monkeypatch, response_queue, observed_request_messages)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Update report-builder documentation if needed.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert any(
        "The final step 'Confluence aktualisieren' has already used enough tool iterations."
        in (message.get("content") or "")
        for request in observed_request_messages
        for message in request
        if message.get("role") == "system"
    )
    assert events[-1].content.startswith(
        "Agent stopped because the final step 'Confluence aktualisieren' kept calling tools without reaching a conclusion."
    )
