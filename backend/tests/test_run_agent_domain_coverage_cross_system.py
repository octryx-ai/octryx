"""run_agent uses the generic cross-system summary coverage for an orders project that spans several systems."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Project, ScenarioProfile, Session, TurnTrace, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


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


def _cross_system_responses():
    return [
        _tool_call_response(
            "call-jira",
            "search_jira_tickets",
            '{"jql": "updated >= -1d ORDER BY updated DESC", "limit": 20}',
            _usage(16, 4),
        ),
        _text_response("Aenderungen gesammelt. Ich wechsle jetzt zur Dokumentationsanalyse.", _usage(16, 4)),
        _tool_call_response(
            "call-bitbucket", "list_recent_bitbucket_commits", '{"days": 1, "per_repo_limit": 10}', _usage(18, 4)
        ),
        _text_response("Dokumentationsbedarf abgeleitet. Ich aktualisiere jetzt Confluence.", _usage(18, 4)),
        _tool_call_response("call-confluence", "search_confluence", '{"limit": 20}', _usage(20, 4)),
        _text_response("Final summary across Jira, Bitbucket, and Confluence.", _usage(24, 6)),
    ]


def _cross_system_coverage_profile(admin, project):
    return ScenarioProfile(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Cross-System Summary Coverage",
        match_config={"route_reasons": ["contextual_request"]},
        execution_config={
            "required_domains": ["jira", "bitbucket", "confluence"],
            "enforce_domain_coverage": True,
        },
        is_active=True,
        priority=10,
    )


def _cross_system_tool_result(tool_name, tool_args):
    if tool_name == "search_jira_tickets":
        return {"query": "", "jql": tool_args.get("jql"), "api_version": "2", "results": []}
    if tool_name == "list_recent_bitbucket_commits":
        return {"days": 1, "total_commit_count": 1, "repositories": []}
    if tool_name == "search_confluence":
        return {
            "project_name": "acme-orders",
            "space_key": "INFRA",
            "total_pages": 1,
            "new_pages": [],
            "changed_pages": [],
            "unchanged_pages": [],
            "removed_pages": [],
        }
    return {}


async def _latest_turn_trace(db, session_id):
    return (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at.desc())
            )
        )
        .scalars()
        .first()
    )


@pytest.mark.asyncio
async def test_run_agent_uses_generic_cross_system_summary_coverage_for_acme_orders_project(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    # Coverage comes from an explicit, route-matched scenario profile (Not from the wording).
    db.add(_cross_system_coverage_profile(admin, project))
    await db.commit()

    response_queue = _cross_system_responses()
    executed_tools: list[str] = []

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _cross_system_tool_result(tool_name, tool_args)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for today.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        db=db,
    ):
        events.append(event)

    assert executed_tools == [
        "search_jira_tickets",
        "list_recent_bitbucket_commits",
        "search_confluence",
    ]
    assert events[-1].content == "Final summary across Jira, Bitbucket, and Confluence."

    trace = await _latest_turn_trace(db, session.id)
    context_plan = trace.context_snapshot_json["context_plan"]
    assert context_plan["scenario_profile_name"] == "Cross-System Summary Coverage"
    assert context_plan["required_domains"] == ["jira", "bitbucket", "confluence"]
    assert context_plan["enforce_domain_coverage"] is True
