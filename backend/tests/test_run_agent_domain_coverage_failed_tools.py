"""Summary coverage ignores failed or static domain tools."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

import app.agent.core.context.run_context_knowledge as run_context_knowledge_module
import app.agent.engine as engine_module
import app.agent.engine._engine_turn_admission as turn_admission_module
from app.agent.engine import (
    run_agent,
)
from app.models import Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _call(call_id, name, arguments):
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _response(content, tool_calls, prompt_tokens, completion_tokens):
    return {
        "content": content,
        "tool_calls": tool_calls,
        "model": "claude-haiku-4.5",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _coverage_responses():
    """A failing Jira query, Bitbucket with an early finish, the missing Jira and Confluence calls, the summary."""
    return [
        _response(
            "Starting with project context and Jira.",
            [
                _call("call-knowledge", "get_project_knowledge_overview", "{}"),
                _call("call-jira-bad", "search_jira_tickets", '{"project_key": "ACME_ORDERS", "limit": 20}'),
            ],
            20,
            5,
        ),
        _response(
            "Bitbucket data collected, I can finish now.",
            [_call("call-bitbucket", "list_recent_bitbucket_commits", '{"days": 7, "per_repo_limit": 10}')],
            25,
            5,
        ),
        _response(
            "Collecting the missing Jira and Confluence deltas now.",
            [
                _call(
                    "call-jira-good",
                    "search_jira_tickets",
                    '{"jql": "updated >= -24h ORDER BY updated DESC", "limit": 20}',
                ),
                _call("call-confluence", "search_confluence", '{"limit": 20}'),
            ],
            30,
            5,
        ),
        _response("Final daily summary across Jira, Bitbucket, and Confluence.", None, 35, 6),
    ]


def _tool_result(tool_name, tool_args):
    if tool_name == "get_project_knowledge_overview":
        return {"project_name": "acme-orders", "entry_count": 350}
    if tool_name == "search_jira_tickets" and tool_args.get("project_key") == "ACME_ORDERS":
        return {"error": "query or jql is required"}
    if tool_name == "search_jira_tickets":
        return {"query": "", "jql": tool_args.get("jql"), "api_version": "2", "results": []}
    if tool_name == "list_recent_bitbucket_commits":
        return {"days": 7, "total_commit_count": 5, "repositories": []}
    if tool_name == "search_confluence":
        return {
            "project_name": "acme-orders",
            "space_key": "INFRA",
            "total_pages": 12,
            "new_pages": [],
            "changed_pages": [],
            "unchanged_pages": [],
            "removed_pages": [],
        }
    return {}


def _allow_execution_gate(monkeypatch):
    from app.services.session.execution_gate import ExecutionGateDecision

    monkeypatch.setattr(
        turn_admission_module,
        "evaluate_execution_gate",
        lambda _profile: ExecutionGateDecision(
            allowed=True, status="allowed", decision_source="test", reason="test", user_message=""
        ),
    )


def _stub_runtime_tools_and_coverage(monkeypatch, response_queue, captured_messages, executed_tools):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        captured_messages.append(messages)
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _tool_result(tool_name, tool_args)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)
    # Explicit coverage settings (as a scenario profile sets them); the planner reads no prompt.
    real_plan_turn_context = run_context_knowledge_module.plan_turn_context
    monkeypatch.setattr(
        run_context_knowledge_module,
        "plan_turn_context",
        lambda **kwargs: replace(
            real_plan_turn_context(**kwargs),
            required_domains=["jira", "bitbucket", "confluence"],
            enforce_domain_coverage=True,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_summary_coverage_ignores_failed_or_static_domain_tools(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    _allow_execution_gate(monkeypatch)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()
    response_queue = _coverage_responses()
    executed_tools = []
    captured_messages = []
    _stub_runtime_tools_and_coverage(monkeypatch, response_queue, captured_messages, executed_tools)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for the last 7 days.",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        events.append(event)

    # get_project_knowledge_overview runs first since the knowledge prefetch
    # work landed; the coverage logic under test still ignores it as a static
    # domain tool.
    assert executed_tools == [
        "get_project_knowledge_overview",
        "search_jira_tickets",
        "list_recent_bitbucket_commits",
        "search_jira_tickets",
        "search_confluence",
    ]
    assert events[-1].content == "Final daily summary across Jira, Bitbucket, and Confluence."
