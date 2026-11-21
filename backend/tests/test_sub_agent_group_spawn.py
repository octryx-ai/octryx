"""Spawning a sub-agent marks the parent waiting, creates the group and carries the parent's coding mode and engineering context."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, SubAgentGroup, User
from app.services.session.run_state import RUN_STATUS_AWAITING_SUBAGENTS, get_session_run_status
from app.services.sub_agent_group import (
    MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
    normalize_sub_agent_group_timeout_seconds,
)
from app.tools.context import ToolContext
from app.tools.sub_agent import SpawnSubAgentTool


def test_normalize_sub_agent_group_timeout_allows_quality_first_long_runs():
    assert normalize_sub_agent_group_timeout_seconds(7_200) == 7_200
    assert normalize_sub_agent_group_timeout_seconds(99_999) == MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_spawn_sub_agent_marks_parent_waiting_and_creates_group(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        metadata_={"title": "Parent orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    result = await tool.execute(
        {"sub_tasks": ["Inspect service alpha", "Inspect service beta"]},
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="diagnosis",
            agent_mode_key="diagnosis",
            turn_context_snapshot={"runtime_target_id": "runtime-1", "thinking_level": "deep"},
            agent_definition={"agentType": "diagnosis"},
        ),
    )

    await db.refresh(parent_session)
    group = (
        await db.execute(select(SubAgentGroup).where(SubAgentGroup.parent_session_id == parent_session.id))
    ).scalar_one()
    child_sessions = (
        (
            await db.execute(
                select(Session).where(Session.parent_session_id == parent_session.id).order_by(Session.started_at.asc())
            )
        )
        .scalars()
        .all()
    )

    assert result["status"] == "awaiting_subagents"
    assert result["sub_agent_group_id"] == group.id
    assert result["count"] == 2
    assert parent_session.status == "awaiting_subagents"
    assert get_session_run_status(parent_session) == RUN_STATUS_AWAITING_SUBAGENTS
    assert len(child_sessions) == 2
    assert all((session.metadata_ or {}).get("allow_workflow_contracts") is False for session in child_sessions)
    assert all((session.metadata_ or {}).get("runtime_request_timeout_seconds") == 30 for session in child_sessions)
    assert group.total_count == 2
    assert launch_calls and launch_calls[0]["group_id"] == group.id


@pytest.mark.asyncio
async def test_spawn_sub_agent_inherits_parent_coding_mode_without_agent_definition(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="coding",
        metadata_={"title": "Parent coding migration orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {"sub_tasks": ["Inspect source compatibility"]},
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="coding",
            agent_mode_key="coding",
            agent_definition=None,
        ),
    )

    child_sessions = (
        (
            await db.execute(
                select(Session).where(Session.parent_session_id == parent_session.id).order_by(Session.started_at.asc())
            )
        )
        .scalars()
        .all()
    )

    assert {session.agent_type for session in child_sessions} == {"coding"}
    assert launch_calls and launch_calls[0]["agent_type"] == "coding"


@pytest.mark.asyncio
async def test_spawn_sub_agent_carries_parent_engineering_context_to_coding_child(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="coding",
        metadata_={"title": "Parent migration with resolved repository"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    engineering_resolution = {
        "prompt_contract": {
            "intent": "coding_migration",
            "stack_key": "java-spring",
            "source_versions": {"java": "21", "spring_boot": "3.4.x"},
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
        },
        "repository": {
            "id": "repo-1",
            "name": "spring-petclinic-rest",
            "repo_root": "/tmp/spring-petclinic-rest-openrewrite-lab",
        },
        "engineering_knowledge_pack": {
            "pack_key": "java-21-to-25-spring-boot-3.4-to-4.0.3",
            "version": 2,
            "quality_status": "passed",
        },
    }

    tool = SpawnSubAgentTool()
    await tool.execute(
        {"sub_tasks": ["Inspect source compatibility"]},
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={
                "engineering_knowledge_runtime_resolution": engineering_resolution,
            },
            current_user_message=(
                "Migriere spring-petclinic-rest-openrewrite-lab von Java 21 und Spring Boot 3.4.x "
                "zu Java 25 und Spring Boot 4.0.3."
            ),
            db=db,
            system_context={},
            capability_type="coding",
            agent_mode_key="coding",
            agent_definition=None,
        ),
    )

    child_session = (
        await db.execute(select(Session).where(Session.parent_session_id == parent_session.id))
    ).scalar_one()
    metadata = child_session.metadata_ or {}
    child_task = launch_calls[0]["child_runs"][0]["task"]

    assert metadata["runtime_request_timeout_seconds"] == 180
    assert metadata["code_repository_id"] == "repo-1"
    assert metadata["engineering_knowledge_repo_search_roots"] == ["/tmp/spring-petclinic-rest-openrewrite-lab"]
    assert metadata["parent_engineering_knowledge_runtime_resolution"] == engineering_resolution
    assert "Parent coding-migration context" in child_task
    assert "spring-petclinic-rest-openrewrite-lab" in child_task
    assert "Java 25" in child_task
    assert "Spring Boot 4.0.3" in child_task
    assert "Inspect source compatibility" in child_task
