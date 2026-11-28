import uuid

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, AgentGroup
from app.services.agent_group import (
    create_agent_group,
    delete_agent_group,
    list_agent_groups,
    serialize_agent_group,
    update_agent_group,
)


@pytest.mark.asyncio
async def test_agent_group_crud_and_serialization_stay_stable(db, auth_user):
    created = await create_agent_group(
        db,
        user_id=auth_user.id,
        payload={
            "name": " Platform / SRE  ",
            "description": "Runtime operations",
            "category": "ops",
            "position": 30,
            "is_active": True,
        },
    )

    assert created["name"] == "Platform / SRE"
    assert created["slug"] == "platform-sre"
    assert created["description"] == "Runtime operations"
    assert created["category"] == "ops"
    assert created["projectId"] == ""
    assert created["position"] == 30
    assert created["isActive"] is True
    assert created["agentCount"] == 0

    group = await db.get(AgentGroup, created["id"])
    assert group is not None
    assert serialize_agent_group(group)["agentCount"] == 0

    db.add(
        AgentDefinition(
            id=str(uuid.uuid4()),
            owner_id=auth_user.id,
            group_id=group.id,
            name="SRE Investigator",
            description="Investigate runtime issues",
            goal="Find the operational fault",
            agent_type="diagnosis",
            thinking_level="deep",
            branch_prefix="octryx",
            system_prompt="Investigate carefully.",
            output_prompt="Summarize findings.",
            is_active=True,
        )
    )
    await db.commit()

    listed_groups = await list_agent_groups(db, user_id=auth_user.id)
    listed_group = next(item for item in listed_groups if item.id == group.id)
    assert serialize_agent_group(listed_group)["agentCount"] == 1

    updated = await update_agent_group(
        db,
        user_id=auth_user.id,
        group_id=group.id,
        payload={
            "name": "Platform Reliability",
            "slug": "Platform & Reliability",
            "description": "Runtime and reliability ownership",
            "category": "platform",
            "project_id": "project-123",
            "position": 15,
            "is_active": False,
        },
    )

    assert updated == {
        "id": group.id,
        "name": "Platform Reliability",
        "slug": "platform-reliability",
        "description": "Runtime and reliability ownership",
        "category": "platform",
        "projectId": "project-123",
        "position": 15,
        "isActive": False,
        "agentCount": 0,
    }

    deleted = await delete_agent_group(db, user_id=auth_user.id, group_id=group.id)
    assert deleted == {"status": "deleted"}
    assert await db.get(AgentGroup, group.id) is None

    detached_agent = (
        await db.execute(select(AgentDefinition).where(AgentDefinition.name == "SRE Investigator"))
    ).scalar_one()
    assert detached_agent.group_id is None
