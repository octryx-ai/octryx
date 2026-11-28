"""Freezing and releasing context checkpoints and blocking tool calls while one is active."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ContextCheckpoint, Session, User
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


