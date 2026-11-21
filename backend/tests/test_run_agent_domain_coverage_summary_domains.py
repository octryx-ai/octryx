"""The agent requires every summary domain before it finishes."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.core.context.run_context_knowledge as run_context_knowledge_module
import app.agent.engine as engine_module
from app.agent.core.context.context_planner import ContextPlan
from app.agent.engine import (
    run_agent,
)
from app.models import Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


async def _summary_project(db, admin):
    # The execution profile gate blocks summary workflows whose planned
    # connector tools are inactive; these tests need active connectors.
    from app.models import UserProject

    project = Project(
        id=str(uuid.uuid4()),
        name=f"domain-coverage-{uuid.uuid4().hex[:6]}",
        is_active=True,
        config={
            "jira_url": "https://jira.example.com",
            "bitbucket_url": "https://bitbucket.example.com",
            "confluence_url": "https://confluence.example.com",
        },
    )
    db.add(project)
    db.add(UserProject(user_id=admin.id, project_id=project.id, role="member"))
    await db.flush()
    return project


def _summary_responses():
    """Bitbucket first, an early finish attempt, then Jira and Confluence, then the final summary."""
    return [
        {
            "content": "Collecting Bitbucket activity first.",
            "tool_calls": [
                {
                    "id": "call-bitbucket",
                    "function": {
                        "name": "list_recent_bitbucket_commits",
                        "arguments": '{"days": 1, "per_repo_limit": 5}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
        {
            "content": "I can finalize the summary now.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
        {
            "content": "Collecting Jira and Confluence activity now.",
            "tool_calls": [
                {
                    "id": "call-jira",
                    "function": {
                        "name": "search_jira_tickets",
                        "arguments": '{"jql": "updated >= -1d ORDER BY updated DESC", "limit": 10}',
                    },
                },
                {
                    "id": "call-confluence",
                    "function": {
                        "name": "search_confluence",
                        "arguments": '{"limit": 10}',
                    },
                },
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 15, "completion_tokens": 4, "total_tokens": 19},
        },
        {
            "content": "Final summary across Jira, Bitbucket, and Confluence.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 18, "completion_tokens": 5, "total_tokens": 23},
        },
    ]


def _tool_result(tool_name):
    if tool_name == "list_recent_bitbucket_commits":
        return {
            "days": 1,
            "cutoff_utc": "2026-03-24T00:00:00+00:00",
            "total_commit_count": 1,
            "repositories": [
                {
                    "project_key": "SHOP",
                    "repo_slug": "acme-orders-catalog-plugin",
                    "label": "SHOP/acme-orders-catalog-plugin",
                    "commit_count": 1,
                    "commits": [
                        {
                            "display_id": "abc123",
                            "message": "docs: update readme",
                            "author_name": "Alice Example",
                            "author_timestamp": 1774368795000,
                        }
                    ],
                }
            ],
        }
    if tool_name == "search_jira_tickets":
        return {
            "query": "",
            "jql": "updated >= -1d ORDER BY updated DESC",
            "api_version": "2",
            "results": [{"ticket_id": "OCX-1", "summary": "Fix docs", "status": "Done", "updated": "2026-03-24"}],
        }
    if tool_name == "search_confluence":
        return {
            "project_name": "acme-orders",
            "space_key": "INFRA",
            "total_pages": 1,
            "new_pages": [],
            "changed_pages": [{"id": "1", "title": "Ops Guide", "current_version": 2, "stored_version": 1}],
            "unchanged_pages": [],
            "removed_pages": [],
        }
    return {}


def _coverage_plan(**kwargs):
    # Explicit coverage: the plan carries the required domains with coverage enforcement, as
    # a scenario profile sets them (No route reads the prompt).
    return ContextPlan(
        tier="standard",
        route_reason="contextual_request",
        token_budget=12000,
        include_tools=True,
        include_system_context=False,
        include_skills=False,
        include_recent_history=True,
        include_summary_context=False,
        domains=["jira", "bitbucket", "confluence"],
        tool_allowlist=None,
        skill_terms=[],
        blocked_tools=[],
        required_domains=["jira", "bitbucket", "confluence"],
        enforce_domain_coverage=True,
        scenario_profile_id="",
        scenario_profile_name="",
        include_agent_blueprint=True,
        system_prompt_variant="full",
        recent_history_limit=12,
    )


def _stub_runtime_tools_and_plan(monkeypatch, response_queue, captured_messages, executed_tools):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        captured_messages.append(messages)
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _tool_result(tool_name)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)
    monkeypatch.setattr(run_context_knowledge_module, "plan_turn_context", _coverage_plan)


@pytest.mark.asyncio
async def test_run_agent_requires_all_summary_domains_before_finishing(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    summary_project = await _summary_project(db, admin)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=summary_project.id,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    captured_messages = []
    executed_tools = []
    response_queue = _summary_responses()
    _stub_runtime_tools_and_plan(monkeypatch, response_queue, captured_messages, executed_tools)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for today.",
        user_id=admin.id,
        project_id=summary_project.id,
        agent_type="diagnosis",
        db=db,
    ):
        events.append(event)

    assert "list_recent_bitbucket_commits" in executed_tools
    assert "search_jira_tickets" in executed_tools
    assert "search_confluence" in executed_tools
    assert events[-1].content == "Final summary across Jira, Bitbucket, and Confluence."
    assert all(
        not str(getattr(event, "content", "") or "").startswith("Hier ist die Tabelle aller Commits")
        for event in events
    )
    assert any(
        any(
            message.get("role") == "system" and "not complete yet" in str(message.get("content") or "")
            for message in request
        )
        for request in captured_messages[2:]
    )
