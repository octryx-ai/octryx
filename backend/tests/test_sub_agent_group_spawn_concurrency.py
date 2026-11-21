"""Spawn options for bounded concurrent children, derived group timeouts and serialized children on SQLite."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.tools.context import ToolContext
from app.tools.sub_agent import SpawnSubAgentTool


@pytest.mark.asyncio
async def test_spawn_sub_agent_forwards_bounded_max_concurrent_children(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent bounded concurrency orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)
    monkeypatch.setattr("app.tools.sub_agent.db_runtime._is_sqlite", False)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Research benefits", "Research risks", "Research rollout"],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
            "max_concurrent": 2,
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="documentation",
            agent_mode_key="documentation",
            turn_context_snapshot={"thinking_level": "deep"},
            agent_definition={"agentType": "documentation"},
        ),
    )

    assert launch_calls
    assert launch_calls[0]["max_concurrent_children"] == 2


@pytest.mark.asyncio
async def test_spawn_sub_agent_derives_group_timeout_for_serialized_quality_children(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent long research orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    create_calls = []
    launch_calls = []

    async def fake_create_sub_agent_group(*args, **kwargs):
        create_calls.append(kwargs)
        return SimpleNamespace(id="group-long-run")

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.create_sub_agent_group", fake_create_sub_agent_group)
    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)
    monkeypatch.setattr("app.tools.sub_agent.db_runtime._is_sqlite", True)

    tool = SpawnSubAgentTool()
    result = await tool.execute(
        {
            "sub_tasks": [f"Research slice {index}" for index in range(5)],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
            "max_concurrent": 5,
            "min_sources_per_child": 3,
            "child_runtime_timeout_seconds": 180,
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="documentation",
            agent_mode_key="documentation",
            turn_context_snapshot={"thinking_level": "deep"},
            agent_definition={"agentType": "documentation"},
        ),
    )

    assert create_calls
    assert create_calls[0]["timeout_seconds"] == 4560
    assert result["timeout_seconds"] == 4560
    assert launch_calls[0]["max_concurrent_children"] == 1


@pytest.mark.asyncio
async def test_spawn_sub_agent_serializes_child_concurrency_on_sqlite(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent sqlite-safe orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)
    monkeypatch.setattr("app.tools.sub_agent.db_runtime._is_sqlite", True)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Research benefits", "Research risks", "Research rollout"],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
            "max_concurrent": 4,
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="documentation",
            agent_mode_key="documentation",
            turn_context_snapshot={"thinking_level": "deep"},
            agent_definition={"agentType": "documentation"},
        ),
    )

    assert launch_calls
    assert launch_calls[0]["max_concurrent_children"] == 1
