from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_disabled_tool_runtime_fails_with_clear_project_policy_error(db):
    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    project_config = {"tool_policy": {"allowlist": ["knowledge_search"]}}
    context = ToolContext(
        db=db,
        project_ids=[demo.id],
        roles=["admin"],
        project_config=project_config,
        user_id="test-user",
        session_id="test-session",
    )

    result = await execute_tool("read_workspace_file", {"path": "README.md"}, context)

    assert result["error"] == "Not included in the project tool visibility allow rules."
    assert result["tool_name"] == "read_workspace_file"
    assert result["policy"] == "project_tool_policy"
