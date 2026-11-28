"""skill_search and skill_get return policy-filtered metadata and load one level, and skill usage traces record and redact what they saw."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, SkillUsageEvent
from app.services.skill_usage_trace_service import summarize_skill_usage
from app.tools.registry import execute_tool
from tests.services.misc.skill_runtime_tools_support import _tool_context
from tests.skill_catalog.support import publish_chat_skill


@pytest.mark.asyncio
async def test_skill_search_returns_metadata_only_and_filters_policy(db, auth_user):
    await publish_chat_skill(db, "daily-summary-method", approver_id=auth_user.id,
                             description="Build a daily operational summary.", category="reporting",
                             body="This full content must not appear in search.",
                             when_to_use="Use for a daily summary.", required_tools=("read_workspace_file",),
                             allowed_roles=("admin",))
    await publish_chat_skill(db, "requires-missing-tool", approver_id=auth_user.id, description="Should be hidden.",
                             category="reporting", when_to_use="Use for a daily summary.",
                             required_tools=("missing_tool",), allowed_roles=("admin",))
    await publish_chat_skill(db, "archived-summary-method", approver_id=auth_user.id,
                             description="Should not be returned by default.", category="reporting",
                             when_to_use="Use for a daily summary.", allowed_roles=("admin",), in_chat=False)
    await db.commit()

    result = await execute_tool(
        "skill_search",
        {"query": "daily summary", "limit": 10},
        _tool_context(db=db, user=auth_user),
    )

    assert "error" not in result
    names = [item["name"] for item in result["results"]]
    assert names == ["daily-summary-method"]
    assert result["results"][0]["summary"] == "Build a daily operational summary."
    assert "full content" not in str(result["results"][0]).lower()
    assert result["results"][0]["available_content_levels"] == ["summary", "card", "full"]


@pytest.mark.asyncio
async def test_skill_get_loads_one_level_and_blocks_non_active_without_diagnostics(db, auth_user):
    skill, _version = await publish_chat_skill(db, "long-skill", approver_id=auth_user.id, description="Short summary",
                                               body="F" * 7000, card_content="Card content",
                                               allowed_roles=("admin",), in_chat=False)
    await db.commit()

    blocked = await execute_tool(
        "skill_get",
        {"skill_id": skill.id, "content_level": "full"},
        _tool_context(db=db, user=auth_user),
    )
    assert blocked["error"] == "Skill is not available in platform chat"

    loaded = await execute_tool(
        "skill_get",
        {"skill_id": skill.id, "content_level": "full", "diagnostics": True},
        _tool_context(db=db, user=auth_user),
    )
    assert loaded["content_level"] == "full"
    assert len(loaded["content"]) == 6000
    assert loaded["truncated"] is True


@pytest.mark.asyncio
async def test_skill_usage_trace_records_search_get_and_admin_summary(db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"skill-trace-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    await db.flush()
    skill, _version = await publish_chat_skill(db, "traceable-skill", approver_id=auth_user.id,
                                               description="Traceable summary", body="Use this traceable workflow.",
                                               when_to_use="Use for a traceable workflow.", allowed_roles=("admin",))
    await db.commit()

    context = _tool_context(db=db, user=auth_user, project_id=project.id)
    context.agent_definition = {"id": "trace-agent"}
    context.request_id = "trace-request-1"

    search_result = await execute_tool(
        "skill_search",
        {"query": "traceable workflow", "project_id": project.id},
        context,
    )
    assert [item["id"] for item in search_result["results"]] == [skill.id]

    get_result = await execute_tool(
        "skill_get",
        {"skill_id": skill.id, "content_level": "full", "project_id": project.id},
        context,
    )
    assert get_result["id"] == skill.id

    events = (
        await db.execute(
            select(SkillUsageEvent)
            .where(SkillUsageEvent.session_id == context.session_id)
            .order_by(SkillUsageEvent.created_at.asc())
        )
    ).scalars().all()
    assert [event.event_type for event in events] == ["search", "get"]
    assert events[0].query_excerpt == "traceable workflow"
    assert events[0].returned_skill_ids == [skill.id]
    assert events[0].project_id == project.id
    assert events[0].agent_id == "trace-agent"
    assert events[0].request_id == "trace-request-1"
    assert events[1].skill_id == skill.id
    assert events[1].skill_version == 1
    assert events[1].content_level == "full"
    assert events[1].token_cost_estimate > 0  # computed from the published instructions
    assert (events[0].surface, events[0].invocation, events[1].invocation) == ("platform_chat", "search", "get")
    assert events[1].bundle_digest.startswith("sha256:")

    summary = await summarize_skill_usage(db)
    assert summary[skill.id]["load_count"] == 1
    assert summary[skill.id]["last_used_at"]
    assert summary[skill.id]["common_queries"] == ["traceable workflow"]


@pytest.mark.asyncio
async def test_skill_usage_trace_redacts_policy_denied_skill_metadata(db, auth_user):
    skill, _version = await publish_chat_skill(db, "admin-only-trace-skill", approver_id=auth_user.id,
                                               description="Hidden to non admins", allowed_roles=("admin",))
    await db.commit()

    context = _tool_context(db=db, user=auth_user, roles=["viewer"])
    result = await execute_tool("skill_get", {"skill_id": skill.id, "content_level": "full"}, context)
    assert result["error"] == "Skill is not allowed for the current user roles"

    event = (
        await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.session_id == context.session_id))
    ).scalar_one()
    assert event.event_type == "policy_denied"
    assert event.policy_status == "denied"
    assert event.skill_id is None
    assert event.skill_name is None
    assert event.skill_version is None
    assert event.token_cost_estimate == 0
    assert event.policy_reason == "Skill is not allowed for the current user roles"
