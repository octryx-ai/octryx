"""prepare_agent_run injects context checkpoints, runtime compaction, the resolved workspace root and the session runtime timeout."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.models import Message, Project, RuntimeContextCompaction, Session, User
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_agent_run_injects_active_context_checkpoint_prompt(db, tmp_path: Path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="change", metadata_={})
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
        turn_context_snapshot={"current_step": {"name": "Release"}},
    )
    frozen = await execute_tool("freeze_context", {"checkpoint_name": "before-release"}, context)
    assert frozen["status"] == "active"

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Continue the release carefully",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert "## Context Checkpoint" in prepared.system_prompt
    assert "before-release" in prepared.system_prompt
    assert "release_context" in prepared.system_prompt


@pytest.mark.asyncio
async def test_prepare_agent_run_injects_runtime_context_compaction_prompt(db, tmp_path: Path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", metadata_={})
    db.add(session)
    messages = []
    for index in range(22):
        role = "user" if index % 2 == 0 else "assistant"
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role=role,
            content=f"{role} long running context message {index}",
            tool_calls=[
                {
                    "id": f"tool-call-{index}",
                    "function": {"name": "knowledge_search"},
                }
            ]
            if role == "assistant"
            else None,
        )
        messages.append(message)
        db.add(message)
    await db.commit()

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Continue the investigation from the previous work.",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert "## Compacted Runtime Context" in prepared.system_prompt
    assert "Active context compaction" in prepared.system_prompt
    assert "Source messages compacted" in prepared.system_prompt
    assert "knowledge_search" in prepared.system_prompt
    assert prepared.session_metadata["runtime_context_compaction"]["source_message_count"] >= 8

    compactions = (
        (await db.execute(select(RuntimeContextCompaction).where(RuntimeContextCompaction.session_id == session.id)))
        .scalars()
        .all()
    )
    assert len(compactions) == 1
    assert compactions[0].status == "active"


@pytest.mark.asyncio
async def test_prepare_agent_run_injects_resolved_workspace_root_into_project_config(
    db, tmp_path: Path, monkeypatch
):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"workspace-root-{uuid.uuid4().hex[:6]}",
        config={"managed_repo_root": "var/repos/bitbucket"},
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="coding", metadata_={})
    db.add_all([project, session])
    await db.commit()

    monkeypatch.setattr(
        "app.agent.core.context.run_context_config.resolve_app_workspace_root",
        lambda: tmp_path.resolve(),
    )

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Implement a focused UI budget warning banner with tests.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path / "session-workspace"),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert prepared.tool_context.project_config["workspace_root"] == str(tmp_path.resolve())
    assert prepared.tool_context.project_config["project_id"] == project.id


@pytest.mark.asyncio
async def test_prepare_agent_run_applies_session_runtime_timeout_override(db, tmp_path: Path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="documentation",
        metadata_={"runtime_request_timeout_seconds": 180},
    )
    db.add(session)
    await db.commit()

    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Research ticketing API integration and summarize the main benefits.",
        user_id=admin.id,
        project_id=None,
        agent_type="documentation",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=lambda definitions, _allow: definitions,
        exclude_tool_definitions=lambda definitions, _blocked: definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )

    assert prepared.runtime_settings["runtime_request_timeout_seconds"] == 180
