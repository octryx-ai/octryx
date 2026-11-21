from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RuntimeProcess, Session, User
from app.services.durable_process_runtime import configure_durable_process_runtime
from app.tools.context import ToolContext
from app.tools.registry import execute_tool

from .conftest import shared_test_session_factory


async def _admin_user(db: AsyncSession) -> User:
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return user


async def _context(db: AsyncSession, tmp_path: Path, user: User) -> ToolContext:
    session = Session(id=f"durable-process-{uuid.uuid4()}", user_id=user.id, metadata_={})
    db.add(session)
    await db.commit()
    return ToolContext(
        user_id=user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        workspace_root=str(tmp_path),
        db=db,
    )


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_runtime_process_tools_start_and_collect_completed_output(db, tmp_path):
    configure_durable_process_runtime(shared_test_session_factory)
    user = await _admin_user(db)
    context = await _context(db, tmp_path, user)
    command = f"{sys.executable} -c \"print('durable-ok')\""

    started = await execute_tool("start_runtime_process", {"command": command, "timeout_sec": 10}, context)
    collected = await execute_tool(
        "collect_runtime_process",
        {"process_id": started["process_id"], "wait_seconds": 5},
        context,
    )

    assert started["status"] == "running"
    assert collected["status"] == "completed"
    assert collected["exit_code"] == 0
    assert "durable-ok" in collected["stdout_tail"]
    row = await db.get(RuntimeProcess, started["process_id"])
    assert row is not None
    assert row.status == "completed"


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_runtime_process_tool_timeout_is_persisted(db, tmp_path):
    configure_durable_process_runtime(shared_test_session_factory)
    user = await _admin_user(db)
    context = await _context(db, tmp_path, user)
    command = f"{sys.executable} -c \"__import__('time').sleep(5)\""

    started = await execute_tool("start_runtime_process", {"command": command, "timeout_sec": 1}, context)
    collected = await execute_tool(
        "collect_runtime_process",
        {"process_id": started["process_id"], "wait_seconds": 4},
        context,
    )

    assert collected["status"] == "timed_out"
    assert collected["error"] == "Runtime process timed out after 1s"
    row = await db.get(RuntimeProcess, started["process_id"])
    assert row is not None
    assert row.status == "timed_out"


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_runtime_process_tools_cancel_running_process(db, tmp_path):
    configure_durable_process_runtime(shared_test_session_factory)
    user = await _admin_user(db)
    context = await _context(db, tmp_path, user)
    command = f"{sys.executable} -c \"__import__('time').sleep(30)\""

    started = await execute_tool("start_runtime_process", {"command": command, "timeout_sec": 60}, context)
    cancelled = await execute_tool("cancel_runtime_process", {"process_id": started["process_id"]}, context)
    collected = await execute_tool(
        "collect_runtime_process",
        {"process_id": started["process_id"], "wait_seconds": 5},
        context,
    )

    assert cancelled["process_id"] == started["process_id"]
    assert collected["status"] == "cancelled"
    assert collected["cancel_requested_at"] is not None


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_runtime_process_tools_do_not_cross_user_boundaries(db, tmp_path):
    configure_durable_process_runtime(shared_test_session_factory)
    user = await _admin_user(db)
    other = User(
        id=str(uuid.uuid4()),
        username=f"other-{uuid.uuid4().hex[:6]}",
        email="other@example.com",
        password_hash="x",
        is_active=True,
    )
    db.add(other)
    await db.commit()
    owner_context = await _context(db, tmp_path, user)
    other_context = await _context(db, tmp_path, other)
    command = f"{sys.executable} -c \"print('private-process')\""

    started = await execute_tool("start_runtime_process", {"command": command, "timeout_sec": 10}, owner_context)
    unauthorized = await execute_tool(
        "poll_runtime_process",
        {"process_id": started["process_id"]},
        other_context,
    )
    await execute_tool(
        "collect_runtime_process",
        {"process_id": started["process_id"], "wait_seconds": 5},
        owner_context,
    )

    assert unauthorized["error"] == "Runtime process not found"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
