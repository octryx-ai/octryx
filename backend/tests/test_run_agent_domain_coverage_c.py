"""Tests for run_agent with the document updater definition."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _document_updater_definition():
    return {
        "name": "Document Updater",
        "branchPrefix": "octryx",
        "steps": [
            {
                "name": "Aenderungen sammeln",
                "isEnabled": True,
                "allowedTools": [
                    "list_recent_bitbucket_commits",
                    "search_jira_tickets",
                    "list_workspace_git_commits",
                ],
            },
            {
                "name": "Dokumentationsbedarf ableiten",
                "isEnabled": True,
                "allowedTools": [
                    "knowledge_search",
                    "list_confluence_pages",
                    "get_confluence_page",
                ],
            },
            {
                "name": "Confluence aktualisieren",
                "isEnabled": True,
                "allowedTools": [
                    "get_confluence_page",
                    "update_confluence_page",
                    "create_confluence_page",
                ],
            },
        ],
    }


def _usage(prompt_tokens, completion_tokens):
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _tool_call_response(call_id, name, arguments, usage):
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": arguments}}],
        "model": "claude-haiku-4.5",
        "usage": usage,
    }


def _text_response(content, usage):
    return {"content": content, "tool_calls": None, "model": "claude-haiku-4.5", "usage": usage}


def _document_updater_responses():
    return [
        _tool_call_response("call-commits", "list_recent_bitbucket_commits", '{"limit": 5}', _usage(16, 4)),
        _text_response("Step 1 complete: relevante Repository-Aenderungen wurden gesammelt.", _usage(17, 4)),
        _tool_call_response("call-knowledge", "knowledge_search", '{"query": "release runbook"}', _usage(18, 4)),
        _text_response("Step 2 complete: der Dokumentationsbedarf wurde abgeleitet.", _usage(19, 4)),
        _tool_call_response(
            "call-update",
            "update_confluence_page",
            '{"page_id": "123", "content": "Updated release notes"}',
            _usage(20, 5),
        ),
        _text_response("Document updater completed Confluence review and update.", _usage(22, 6)),
    ]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_document_updater_template_definition_executes_expected_step_flow(db, monkeypatch):
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
    response_queue = _document_updater_responses()
    executed_tools: list[str] = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        if tool_name == "list_recent_bitbucket_commits":
            return {"commits": [{"hash": "abc123", "message": "feat: update release flow"}]}
        if tool_name == "knowledge_search":
            return {
                "state": "ok",
                "result_count": 1,
                "evidence": [{"source_title": "Release runbook", "text": "Release flow steps."}],
            }
        if tool_name == "update_confluence_page":
            return {"page_id": "123", "status": "updated"}
        return {}

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Pruefe die letzten Aenderungen und aktualisiere die betroffene Confluence-Dokumentation.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert executed_tools == [
        "list_recent_bitbucket_commits",
        "knowledge_search",
        "update_confluence_page",
    ]
    assert events[-1].content == "Document updater completed Confluence review and update."
