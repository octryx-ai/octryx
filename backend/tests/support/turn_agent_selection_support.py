"""Shared helpers for the test_turn_agent_selection_* modules."""

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.models import AgentDefinition, Project, User
from app.models import Session as AgentSession
from app.services.workspace_composition import seed_workspace_bundle_foundation


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


def _agent(owner_id: str, project_id: str, name: str, *, agent_type: str = "change") -> AgentDefinition:
    return AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        project_id=project_id,
        name=name,
        description=f"{name} fixture",
        goal="Answer the request",
        agent_type=agent_type,
        thinking_level="light",
        is_active=True,
    )


async def _workspace(db, *, default_agent: bool) -> SimpleNamespace:
    admin = await _admin(db)
    project = Project(id=str(uuid.uuid4()), name=f"agent-selection-{uuid.uuid4()}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    suffix = uuid.uuid4().hex[:6]
    agents = {
        role: _agent(admin.id, project.id, f"{role.title()} Agent {suffix}")
        for role in ("explicit", "session", "mention", "default")
    }
    if default_agent:
        project.config = {"project_agent_preferences": {agents["default"].id: {"status": "primary"}}}
    db.add_all(agents.values())
    await db.commit()
    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    project.config = {}
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"bound_agent_definition_id": agents["session"].id},
    )
    db.add_all([project, session])
    await db.commit()
    return SimpleNamespace(admin=admin, project=project, agents=agents, session=session)
