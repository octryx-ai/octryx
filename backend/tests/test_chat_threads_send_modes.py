"""Chat send and bootstrap keep the explicit project, runtime, thinking and strategy choices without preselecting defaults."""

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AgentDefinition,
    Project,
    User,
)
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_chat_bootstrap_new_thread_does_not_preselect_project_defaults(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name="neutral-entrypoint-project",
        config={"project_agent_preferences": {}},
        is_active=True,
    )
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Neutral Default Delivery Agent",
        description="Coordinates delivery work.",
        goal="Coordinate delivery work",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    db.add_all([project, agent])
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?new=true&project_id={project.id}")

    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["newThread"] is True
    assert payload["selectedProjectId"] == project.id
    assert payload["selectedAgentId"] == ""
    assert payload["selectedAgentName"] == ""
    assert payload["selectedAgentSelectionSource"] == ""
    assert payload["selectedAgentType"] == "diagnosis"
