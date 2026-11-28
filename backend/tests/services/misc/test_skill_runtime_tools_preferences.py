"""skill_search respects project skill bindings, the project none and blocked modes, and the agent's blocked and preferred skills."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.skill_assignment_service import update_project_skill_assignments
from app.tools.registry import execute_tool
from tests.services.misc.skill_runtime_tools_support import _tool_context
from tests.skill_catalog.support import publish_chat_skill


@pytest.mark.asyncio
async def test_skill_search_respects_project_skill_bindings_when_present(db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"skill-project-{uuid.uuid4().hex[:6]}", is_active=True)
    allowed, _ = await publish_chat_skill(db, "project-allowed-skill", approver_id=auth_user.id, description="Allowed",
                                       when_to_use="Use for a project skill.", allowed_roles=("admin",))
    hidden, _ = await publish_chat_skill(db, "project-hidden-skill", approver_id=auth_user.id, description="Hidden",
                                      when_to_use="Use for a project skill.", allowed_roles=("admin",))
    db.add(project)
    await db.commit()
    await update_project_skill_assignments(
        db,
        project_id=project.id,
        payload={"assignment_mode": "selected_only", "selected_skill_ids": [allowed.id]},
    )

    result = await execute_tool(
        "skill_search",
        {"query": "project skill", "project_id": project.id},
        _tool_context(db=db, user=auth_user, project_id=project.id),
    )

    assert [item["name"] for item in result["results"]] == ["project-allowed-skill"]


@pytest.mark.asyncio
async def test_skill_search_respects_project_none_and_blocked_modes(db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"skill-policy-{uuid.uuid4().hex[:6]}", is_active=True)
    skill, _ = await publish_chat_skill(db, "blocked-project-skill", approver_id=auth_user.id, description="Blocked",
                                     when_to_use="Use for a blocked skill.", allowed_roles=("admin",))
    db.add(project)
    await db.commit()

    await update_project_skill_assignments(
        db,
        project_id=project.id,
        payload={"assignment_mode": "all_active", "blocked_skill_ids": [skill.id]},
    )
    blocked = await execute_tool(
        "skill_search",
        {"query": "blocked skill", "project_id": project.id},
        _tool_context(db=db, user=auth_user, project_id=project.id),
    )
    assert blocked["results"] == []

    await update_project_skill_assignments(db, project_id=project.id, payload={"assignment_mode": "none"})
    disabled = await execute_tool(
        "skill_search",
        {"query": "blocked skill", "project_id": project.id},
        _tool_context(db=db, user=auth_user, project_id=project.id),
    )
    assert disabled["results"] == []


@pytest.mark.asyncio
async def test_skill_search_respects_agent_blocked_and_preferred_preferences(db, auth_user):
    preferred, _ = await publish_chat_skill(db, "preferred-skill", approver_id=auth_user.id, description="Preferred",
                                         when_to_use="Use for a shared method.", allowed_roles=("admin",))
    blocked, _ = await publish_chat_skill(db, "agent-blocked-skill", approver_id=auth_user.id, description="Blocked",
                                       when_to_use="Use for a shared method.", allowed_roles=("admin",))
    await db.commit()

    context = _tool_context(db=db, user=auth_user)
    context.agent_definition = {
        "skillPreferences": {
            "preferred_skill_ids": [preferred.id],
            "blocked_skill_ids": [blocked.id],
        }
    }
    result = await execute_tool("skill_search", {"query": "shared method"}, context)

    assert [item["name"] for item in result["results"]] == ["preferred-skill"]
    assert "agent_preferred" in result["results"][0]["match_reason"]
