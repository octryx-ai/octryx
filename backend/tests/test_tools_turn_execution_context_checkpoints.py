"""Freezing and releasing context checkpoints and blocking tool calls while one is active."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import ContextCheckpoint, Message, Session, User
from app.services.context_checkpoint import get_active_context_checkpoint
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_freeze_and_release_context_tools_manage_checkpoints(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
        turn_context_snapshot={"current_step": {"name": "Deploy"}, "turn_diff": {"tool_calls": []}},
    )

    frozen = await execute_tool("freeze_context", {"checkpoint_name": "before-deploy"}, context)
    assert frozen["status"] == "active"
    assert frozen["checkpoint_name"] == "before-deploy"
    assert frozen["tool_calls_blocked_until_release"] is True

    checkpoint = await get_active_context_checkpoint(db, session_id=session.id)
    assert checkpoint is not None
    assert checkpoint.checkpoint_name == "before-deploy"
    assert checkpoint.context_snapshot_json["current_step"]["name"] == "Deploy"

    released = await execute_tool("release_context", {"action": "rollback"}, context)
    assert released["status"] == "rolled_back"

    checkpoints = (
        (await db.execute(select(ContextCheckpoint).where(ContextCheckpoint.session_id == session.id))).scalars().all()
    )
    assert len(checkpoints) == 1
    assert checkpoints[0].status == "rolled_back"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_blocks_calls_when_context_checkpoint_is_active(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id=admin.id, metadata_={})
    db.add(session)
    message = Message(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content="checkpointed")
    db.add(message)
    await db.commit()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session_id,
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
        turn_context_snapshot={"current_step": {"name": "Deploy"}},
    )
    frozen = await execute_tool("freeze_context", {"checkpoint_name": "before-prod"}, context)
    assert frozen["status"] == "active"

    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"failed_count": 2}

    result = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=message.id,
        tool_call={
            "id": "call-k8s-blocked",
            "function": {
                "name": "list_failed_pods",
                "arguments": json.dumps({"namespace": "prod"}),
            },
        },
        tool_context=context,
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={"current_step": {"name": "Deploy"}},
    )

    assert "Context is frozen under checkpoint 'before-prod'" in result.tool_result["result"]["error"]
    assert execution_count["count"] == 0

    release = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=message.id,
        tool_call={
            "id": "call-release",
            "function": {
                "name": "release_context",
                "arguments": json.dumps({"action": "release"}),
            },
        },
        tool_context=context,
        active_steps=[{"name": "Deploy", "allowedTools": ["list_failed_pods"]}],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names={"list_failed_pods"},
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, result: result,
        summary_domains_satisfied_by_result=lambda tool_name, result: set(),
        execute_tool=lambda tool_name, tool_args, tool_context: execute_tool(tool_name, tool_args, tool_context),
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={"current_step": {"name": "Deploy"}},
    )
    assert release.tool_result["result"]["status"] == "released"
