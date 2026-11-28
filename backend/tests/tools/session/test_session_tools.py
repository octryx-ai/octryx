import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.tools.context import ToolContext
from app.tools.session_tools import PlanExitTool, TodoReadTool, TodoWriteTool


@pytest.mark.asyncio
async def test_todo_read_returns_empty_list_on_sqlalchemy_error(db, monkeypatch):
    async def fake_execute(*args, **kwargs):
        raise SQLAlchemyError("read failed")

    monkeypatch.setattr(db, "execute", fake_execute)

    result = await TodoReadTool().execute(
        {},
        ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=".",
        ),
    )

    assert result["todos"] == []
    assert result["summary"]["total"] == 0


@pytest.mark.asyncio
async def test_todo_write_returns_error_on_sqlalchemy_error(db, monkeypatch):
    async def fake_execute(*args, **kwargs):
        raise SQLAlchemyError("write failed")

    monkeypatch.setattr(db, "execute", fake_execute)

    result = await TodoWriteTool().execute(
        {"todos": [{"id": "t1", "subject": "Investigate", "status": "pending"}]},
        ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=".",
        ),
    )

    assert result["error"] == "Failed to save todos: write failed"


@pytest.mark.asyncio
async def test_plan_exit_ignores_sqlalchemy_error(db, monkeypatch):
    async def fake_execute(*args, **kwargs):
        raise SQLAlchemyError("plan save failed")

    monkeypatch.setattr(db, "execute", fake_execute)

    result = await PlanExitTool().execute(
        {"plan": "1. check logs", "summary": "ready"},
        ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id=str(uuid.uuid4()),
            project_config={},
            db=db,
            workspace_root=".",
        ),
    )

    assert result["status"] == "plan_ready"
    assert result["summary"] == "ready"
