"""run_agent keeps step tools under a narrow context allowlist and skips domain coverage when it is not enforced."""

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


async def _seed_running_session(db) -> tuple[User, Project, Session]:
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
    return admin, project, session


def _document_updater_agent(*, step_name: str, instructions: str, success_criteria: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Document Updater",
        "steps": [
            {
                "name": step_name,
                "stepType": "change",
                "instructions": instructions,
                "successCriteria": success_criteria,
                "allowedTools": ["update_confluence_page"],
                "isEnabled": True,
            }
        ],
    }


def _update_page_then_answer_responses(*, arguments: str, final_content: str) -> list[dict]:
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-update",
                    "function": {
                        "name": "update_confluence_page",
                        "arguments": arguments,
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "content": final_content,
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
    ]


def _stub_runtime(monkeypatch, response_queue: list[dict], observed_tool_names: list[list[str]], execute_tool) -> None:
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        observed_tool_names.append([tool["function"]["name"] for tool in (tools or [])])
        return response_queue.pop(0), runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", execute_tool)


def _stub_context_plan(
    monkeypatch,
    *,
    tier: str,
    route_reason: str,
    token_budget: int,
    domains: list[str],
    tool_allowlist: list[str],
    skill_terms: list[str],
    required_domains: list[str],
) -> None:
    monkeypatch.setattr(
        run_context_knowledge_module,
        "plan_turn_context",
        lambda **kwargs: ContextPlan(
            tier=tier,
            route_reason=route_reason,
            token_budget=token_budget,
            include_tools=True,
            include_system_context=False,
            include_skills=False,
            include_recent_history=True,
            include_summary_context=False,
            domains=list(domains),
            tool_allowlist=list(tool_allowlist),
            skill_terms=list(skill_terms),
            blocked_tools=[],
            required_domains=list(required_domains),
            enforce_domain_coverage=False,
            scenario_profile_id=None,
            scenario_profile_name=None,
            include_agent_blueprint=True,
            system_prompt_variant="full",
            recent_history_limit=12,
        ),
    )


async def _collect_run_agent_events(db, admin: User, project: Project, session: Session, user_message: str, agent_definition: dict) -> list:
    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message=user_message,
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)
    return events


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_keeps_step_tools_even_when_context_allowlist_is_narrow(db, monkeypatch):
    admin, project, session = await _seed_running_session(db)

    agent_definition = _document_updater_agent(
        step_name="Confluence aktualisieren",
        instructions="Update the identified page when needed.",
        success_criteria="The page was updated or a clear no-op explanation was given.",
    )

    observed_tool_names: list[list[str]] = []
    response_queue = _update_page_then_answer_responses(
        arguments='{"page_id": "100001", "title": "Report Builder guide", "content": "<p>Updated</p>"}',
        final_content="Updated the report-builder page with the latest findings.",
    )

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        return {"page_id": tool_args["page_id"], "updated": True}

    _stub_runtime(monkeypatch, response_queue, observed_tool_names, fake_execute_tool_with_plugins)
    _stub_context_plan(
        monkeypatch,
        tier="standard",
        route_reason="default_standard",
        token_budget=12000,
        domains=[],
        tool_allowlist=["search_confluence"],
        skill_terms=[],
        required_domains=[],
    )

    events = await _collect_run_agent_events(
        db, admin, project, session, "Update the report-builder documentation page.", agent_definition
    )

    assert observed_tool_names
    assert "update_confluence_page" in observed_tool_names[0]
    assert events[-1].content == "Updated the report-builder page with the latest findings."


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_skips_domain_coverage_when_not_enforced(db, monkeypatch):
    admin, project, session = await _seed_running_session(db)

    agent_definition = _document_updater_agent(
        step_name="Update the runbook page",
        instructions="Update the runbook page with the reviewed change.",
        success_criteria="The runbook page is updated.",
    )

    observed_tool_names: list[list[str]] = []
    response_queue = _update_page_then_answer_responses(
        arguments='{"page_id": "1", "content": "Updated runbook"}',
        final_content="Runbook page updated. No further steps required.",
    )

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        assert tool_name == "update_confluence_page"
        return {"id": "1", "version": 2, "status": "updated"}

    _stub_runtime(monkeypatch, response_queue, observed_tool_names, fake_execute_tool_with_plugins)
    _stub_context_plan(
        monkeypatch,
        tier="full",
        route_reason="change_or_continuation",
        token_budget=24000,
        domains=["bitbucket", "confluence"],
        tool_allowlist=[],
        skill_terms=["bitbucket", "confluence"],
        required_domains=["bitbucket", "confluence"],
    )

    events = await _collect_run_agent_events(
        db, admin, project, session, "Update the runbook page with the reviewed change.", agent_definition
    )

    assert observed_tool_names == [
        ["update_confluence_page"],
        ["update_confluence_page"],
    ]
    assert events[-1].content == "Runbook page updated. No further steps required."
    assert response_queue == []
