"""run_agent advances from a stagnating analysis step after repeated Jira searches."""

import json
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

_SMALL_USAGE = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}


async def _seed_change_session(db, admin, project) -> Session:
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
    return session


def _document_updater_definition() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Document Updater",
        "steps": [
            {
                "name": "Aenderungen sammeln",
                "stepType": "analysis",
                "instructions": "Collect repository evidence and use Jira context only when it helps identify the scope.",
                "successCriteria": "Relevant changes and impacted components are identified.",
                "allowedTools": [
                    "prepare_bitbucket_repository",
                    "git_change_summary",
                    "analyze_workspace_repository",
                    "search_jira_tickets",
                ],
                "isEnabled": True,
            },
            {
                "name": "Dokumentationsbedarf ableiten",
                "stepType": "documentation",
                "instructions": "Summarize the documentation impact based on the evidence.",
                "successCriteria": "The likely documentation scope is clear.",
                "allowedTools": ["search_confluence"],
                "isEnabled": True,
            },
        ],
    }


def _tool_call_response(call_id, name, arguments, usage=_SMALL_USAGE) -> dict:
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": arguments}}],
        "model": "claude-haiku-4.5",
        "usage": dict(usage),
    }


def _model_responses() -> list[dict]:
    """The scripted model turns: repository evidence, four Jira searches, Confluence, then the answer."""
    return [
        _tool_call_response(
            "call-prepare",
            "prepare_bitbucket_repository",
            '{"project_key": "SHOP", "repo_slug": "aws-shop-deployment"}',
        ),
        _tool_call_response("call-summary", "git_change_summary", '{"cwd": "/tmp/repo", "days": 14}'),
        _tool_call_response("call-analyze", "analyze_workspace_repository", '{"path": "/tmp/repo"}'),
        *[
            _tool_call_response(f"call-jira-{index}", "search_jira_tickets", json.dumps({"query": query, "limit": 10}))
            for index, query in enumerate(
                [
                    "report-builder",
                    "Report Builder version",
                    "ACME-423",
                    "ACME-390",
                ],
                start=1,
            )
        ],
        _tool_call_response(
            "call-confluence",
            "search_confluence",
            '{"query": "report-builder operational page", "limit": 5}',
            usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        ),
        {
            "content": "The documentation impact is limited to the report-builder operational Confluence page.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        },
    ]


def _tool_result(tool_name, tool_args) -> dict:
    if tool_name == "prepare_bitbucket_repository":
        return {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-deployment",
            "local_path": "/tmp/repo",
            "relative_path": "var/repos/bitbucket/SHOP/aws-shop-deployment",
            "branch_name": "octryx/test",
        }
    if tool_name == "git_change_summary":
        return {
            "period": "last_14_days",
            "summary": {"total_commits": 12, "bug_fixes": [{"message": "report-builder memory tuning"}]},
        }
    if tool_name == "analyze_workspace_repository":
        return {
            "path": "/tmp/repo",
            "readme_files": ["README.md"],
            "top_level_directories": ["acme-orders-stack-tools"],
        }
    if tool_name == "search_confluence":
        return {
            "query": tool_args.get("query"),
            "results": [{"page_id": "100001", "title": "Report Builder guide"}],
        }
    return {
        "query": tool_args.get("query"),
        "results": [{"ticket_id": "ACME-423", "summary": "report-builder related change"}],
    }


def _patch_engine(monkeypatch, response_queue) -> tuple[list[list[dict[str, str]]], list[str]]:
    """Scripts the model and the tools; returns the observed request messages and the executed tool names."""
    observed_request_messages: list[list[dict[str, str]]] = []
    executed_tools: list[str] = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        observed_request_messages.append(messages)
        return response_queue.pop(0), runtimes[0]
    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _tool_result(tool_name, tool_args)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)
    return observed_request_messages, executed_tools


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_advances_from_stagnating_analysis_step_after_repeated_jira_searches(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = await _seed_change_session(db, admin, project)
    agent_definition = _document_updater_definition()
    observed_request_messages, executed_tools = _patch_engine(monkeypatch, _model_responses())

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Pruefe die letzten report-builder-Aenderungen und leite den Doku-Bedarf ab.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert executed_tools == [
        "prepare_bitbucket_repository",
        "git_change_summary",
        "analyze_workspace_repository",
        "search_jira_tickets",
        "search_jira_tickets",
        "search_jira_tickets",
        "search_jira_tickets",
        "search_confluence",
    ]
    assert any(
        "repository evidence is already available and the run keeps expanding Jira searches"
        in (message.get("content") or "")
        for request in observed_request_messages
        for message in request
        if message.get("role") == "system"
    )
    assert any(
        (event.content or "").startswith("The documentation impact is limited")
        for event in events
        if event.role == "assistant"
    )
