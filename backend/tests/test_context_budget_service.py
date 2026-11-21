import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.context_planner import ContextPlan
from app.agent.core.context.run_context import prepare_agent_run
from app.models import Message, Project, Session, UsageEvent, User
from app.services.context_budget import apply_adaptive_context_budget, list_context_budget_profiles


@pytest.mark.asyncio
async def test_context_budget_profiles_seed_defaults(db):
    profiles = await list_context_budget_profiles(db)
    names = {row["name"] for row in profiles}
    # Every default trigger matches explicit tokens only; the prompt-keyword profiles are gone.
    assert names == {"Sub-Agent Focused", "Change Worker", "Admin Control Plane", "Contextual Standard"}


@pytest.mark.asyncio
async def test_prepare_agent_run_applies_adaptive_token_budget_from_profile_and_history(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"context-budget-{uuid.uuid4().hex[:6]}")
    current_session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    historical_sessions = [
        Session(
            id=str(uuid.uuid4()),
            user_id=user.id,
            project_id=project.id,
            agent_type="diagnosis",
            status="completed",
            metadata_={},
        ),
        Session(
            id=str(uuid.uuid4()),
            user_id=user.id,
            project_id=project.id,
            agent_type="diagnosis",
            status="completed",
            metadata_={},
        ),
    ]
    db.add(project)
    db.add(current_session)
    db.add_all(historical_sessions)
    await db.flush()
    db.add_all(
        [
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=historical_sessions[0].id,
                user_id=user.id,
                provider="openai",
                model="gpt-4.1-mini",
                tokens_in=8000,
                tokens_out=4000,
            ),
            UsageEvent(
                id=str(uuid.uuid4()),
                session_id=historical_sessions[1].id,
                user_id=user.id,
                provider="openai",
                model="gpt-4.1-mini",
                tokens_in=9000,
                tokens_out=5000,
            ),
            Message(
                id=str(uuid.uuid4()),
                session_id=current_session.id,
                role="assistant",
                content="Earlier incident context exists.",
            ),
        ]
    )
    await db.commit()

    async def fake_resolve_model_context_cap(_db, runtime_target_id=None):
        return None

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return []

    prepared = await prepare_agent_run(
        db=db,
        session_id=current_session.id,
        user_message="Create a daily summary from Jira, Bitbucket and Confluence for today.",
        user_id=user.id,
        project_id=project.id,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="deep",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root="/srv/octryx",
        resolve_model_context_cap=fake_resolve_model_context_cap,
        resolve_control_plane_runtimes_func=fake_resolve_control_plane_runtimes,
        filter_tool_definitions=lambda definitions, _allowlist: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    # The summary wording picks no profile; the explicit route does.
    assert prepared.context_plan.budget_profile_name == "Contextual Standard"
    assert prepared.context_plan.similar_session_avg_tokens >= 13000
    assert prepared.context_plan.token_budget >= 14000
    assert (prepared.context_plan.budget_breakdown or {}).get("historical_boost", 0) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_reason", "has_parent_context", "profile_name"),
    [
        ("contextual_request", False, "Contextual Standard"),
        ("change_or_continuation", False, "Change Worker"),
        ("contextual_request", True, "Sub-Agent Focused"),
    ],
)
async def test_budget_profile_follows_the_explicit_route(db, route_reason, has_parent_context, profile_name):
    plan = ContextPlan(
        tier="standard",
        include_tools=True,
        include_system_context=False,
        include_skills=False,
        include_recent_history=True,
        include_summary_context=False,
        include_agent_blueprint=False,
        recent_history_limit=6,
        system_prompt_variant="standard",
        route_reason=route_reason,
        token_budget=10000,
        domains=[],
        tool_allowlist=None,
        skill_terms=[],
        blocked_tools=[],
        required_domains=[],
        enforce_domain_coverage=False,
        scenario_profile_id="",
        scenario_profile_name="",
    )

    updated = await apply_adaptive_context_budget(
        db,
        context_plan=plan,
        project_id=None,
        agent_type="diagnosis",
        capability_type="diagnosis",
        history_count=0,
        entity_count=0,
        tool_count=2,
        has_parent_context=has_parent_context,
        sub_agent_depth=0,
    )

    assert updated.budget_profile_name == profile_name
