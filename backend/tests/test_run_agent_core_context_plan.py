"""run_agent offers the governed surface for a cross-system summary and caps the context plan to the model budget."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import LLMModel, LLMProvider, Project, Session, TurnTrace, User
from app.services.control_plane_service import upsert_runtime_target
from tests.connection_support import connect
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


async def _cross_source_project(db) -> Project:
    """A project whose Jira, Bitbucket and Confluence connectors are active: each through a named connection.

    The cross-source summary requires those connectors; without them the turn ends in
    an explicit needs_configuration state before any model call.
    """
    project = Project(id=str(uuid.uuid4()), name=f"cross-source-summary-{uuid.uuid4().hex[:6]}", config={},
                      is_active=True)
    db.add(project)
    await db.flush()
    for tool in ("jira", "bitbucket", "confluence"):
        await connect(db, tool, project.id)
    return project


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_offers_the_governed_surface_for_a_cross_system_summary(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = await _cross_source_project(db)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    captured = {}

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return (
            {
                "content": "Summary planning",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for today.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        db=db,
    ):
        continue

    system_prompt = captured["messages"][0]["content"]
    tool_names = [item["function"]["name"] for item in (captured["tools"] or [])]
    # A chat turn sends its core tools in full and lists the others by name in tool_search (like the
    # client): offered means either.
    listing = next((item["function"]["description"] for item in captured["tools"] or []
                    if item["function"]["name"] == "tool_search"), "")
    tool_names += [name for name in ("list_recent_bitbucket_commits", "search_confluence", "search_jira_tickets")
                   if name in listing]
    assert "list_recent_bitbucket_commits" in tool_names
    # The Confluence summary domain uses search_confluence (CQL lastmodified);
    # the retired list_confluence_page_updates is gone.
    assert "search_confluence" in tool_names
    assert "search_jira_tickets" in tool_names
    # No keyword narrowing; the provider cap trims the governed default deterministically.
    assert len(tool_names) <= 96
    assert "alert-diagnosis" not in system_prompt
    assert "cluster-health" not in system_prompt


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_caps_context_plan_to_model_budget(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="summary/model",
        display_name="Summary Model",
        context_length=128000,
        planner_context_budget=6000,
        supports_tools=True,
        is_active=True,
    )
    db.add(model)
    await db.flush()
    target = await upsert_runtime_target(
        db,
        provider=provider,
        model_id=model.model_id,
        make_primary=True,
    )
    project = await _cross_source_project(db)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [
            {
                "provider_name": "openrouter",
                "model": model.model_id,
                "target_id": target.id,
            }
        ]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "Summary output",
                "tool_calls": None,
                "model": model.model_id,
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
            runtimes[0],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for today.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        db=db,
        runtime_target_id=target.id,
    ):
        continue

    trace = (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert trace is not None
    context_plan = trace.context_snapshot_json["context_plan"]
    assert context_plan["token_budget"] == 6000
