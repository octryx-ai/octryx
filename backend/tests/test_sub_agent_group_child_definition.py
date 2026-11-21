"""Child agent definitions: repository coding children, a consolidated Java Spring delegation, and disabled or bounded inheritance."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, SubAgentGroup, ToolCall, User
from app.services.sub_agent_group import create_sub_agent_group
from app.tools.context import ToolContext
from app.tools.sub_agent import SpawnSubAgentTool


@pytest.mark.asyncio
async def test_spawn_sub_agent_blocks_second_java_spring_delegation_after_consolidation(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="coding",
        metadata_={"title": "Parent migration after delegated discovery"},
    )
    db.add(parent_session)
    await db.flush()
    await create_sub_agent_group(
        db,
        parent_session_id=parent_session.id,
        child_session_ids=["child-1"],
    )
    db.add(
        ToolCall(
            session_id=parent_session.id,
            tool_name="get_context_from_subthreads",
            parameters={},
            result={"summary": {"completed": 1}},
            status="success",
        )
    )
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    result = await tool.execute(
        {"sub_tasks": ["Run another broad compliance delegation"]},
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={
                "engineering_knowledge_runtime_resolution": {
                    "prompt_contract": {
                        "intent": "coding_migration",
                        "stack_key": "java-spring",
                        "target_versions": {"java": "25", "spring_boot": "4.0.3"},
                    },
                },
            },
            current_user_message="Migriere spring-petclinic-rest zu Java 25 und Spring Boot 4.0.3.",
            db=db,
            system_context={},
            capability_type="coding",
            agent_mode_key="coding",
            agent_definition=None,
        ),
    )

    child_count = (
        await db.execute(select(Session).where(Session.parent_session_id == parent_session.id))
    ).scalars().all()

    assert result["status"] == "blocked"
    assert "Continue in the parent session" in result["error"]
    assert launch_calls == []
    assert child_count == []


@pytest.mark.asyncio
async def test_spawn_sub_agent_builds_repository_coding_child_definition_and_runtime(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="coding",
        metadata_={"title": "Parent migration delegation"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Inspect source compatibility"],
            "inherit_agent_definition": False,
            "child_agent_type": "coding",
            "child_allowed_tools": ["analyze_workspace_repository", "read_workspace_file"],
        },
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

    # Use-case tags do not pick the child's model; without a parent choice or
    # an explicit Workspace default the child runs automatically (the platform order, bounded by the Workspace).
    assert launch_calls[0]["runtime_target_id"] is None
    child_session = (await db.execute(select(Session).where(Session.parent_session_id == parent_session.id))).scalar_one()
    assert not (child_session.metadata_ or {}).get("runtime_target_id")
    child_definition = launch_calls[0]["agent_definition"]
    assert child_definition["agentType"] == "coding"
    assert "repository tool call" in child_definition["prompt"]
    assert "do not inspect repositories" not in child_definition["prompt"].lower()
    assert child_definition["steps"][0]["allowedTools"] == ["analyze_workspace_repository", "read_workspace_file"]


@pytest.mark.asyncio
async def test_spawn_sub_agent_can_disable_agent_definition_inheritance_for_child_document_runs(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="admin",
        metadata_={"title": "Parent document orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    result = await tool.execute(
        {
            "sub_tasks": ["Research benefits", "Research risks"],
            "inherit_agent_definition": False,
            "child_agent_type": "admin",
            "resume_prompt": "Resume the document flow and consolidate subthread evidence.",
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="admin",
            agent_mode_key="admin",
            turn_context_snapshot={"runtime_target_id": "runtime-1", "thinking_level": "deep"},
            agent_definition={"agentType": "admin", "name": "Research Writer"},
        ),
    )

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
    assert group.resume_prompt == "Resume the document flow and consolidate subthread evidence."
    assert {session.agent_type for session in child_sessions} == {"admin"}
    assert launch_calls and launch_calls[0]["agent_definition"] is None


@pytest.mark.asyncio
async def test_spawn_sub_agent_can_attach_bounded_child_agent_definition(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent bounded orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Research benefits"],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
            "child_allowed_tools": ["web_search", "ingest_document_source", "web_fetch"],
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
            turn_context_snapshot={"runtime_target_id": "runtime-1", "thinking_level": "deep"},
            agent_definition={"agentType": "documentation"},
        ),
    )

    assert launch_calls
    child_agent_definition = launch_calls[0]["agent_definition"]
    assert child_agent_definition["name"] == "Delegated Sub-task Worker"
    assert child_agent_definition["agentType"] == "documentation"
    assert "first assistant response must be an allowed tool call" in child_agent_definition["prompt"]
    assert "explicit authoritative URLs" in child_agent_definition["prompt"]
    assert child_agent_definition["steps"][0]["name"] == "Gather Delegated Evidence"
    assert "explicit authoritative URLs" in child_agent_definition["steps"][0]["instructions"]
    assert "your next response must be another allowed tool call" in child_agent_definition["steps"][0]["instructions"]
    assert child_agent_definition["steps"][0]["allowedTools"] == ["web_search", "ingest_document_source", "web_fetch"]
    assert child_agent_definition["steps"][0]["stepConfig"] == {
        "tool_use": "required",
        "max_iterations": 3,
        "max_transitional_responses": 2,
    }
