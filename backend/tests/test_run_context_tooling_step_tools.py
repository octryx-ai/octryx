"""Tool definitions re-add enabled step tools after filtering, record loader failures and keep DB and read-only policies after the re-add."""

from __future__ import annotations

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins


@pytest.mark.asyncio
async def test_execute_tool_with_plugins_blocks_write_tool_for_project_read_only_policy() -> None:
    result = await execute_tool_with_plugins(
        "write_workspace_file",
        {"path": "notes.txt", "content": "hello"},
        ToolContext(
            user_id="user-1",
            project_ids=["support-project"],
            roles=["support"],
            session_id="session-1",
            project_config={"project_role": "support"},
            db=None,
            workspace_root="/tmp/workspace",
        ),
    )

    assert result["policy"] == "project_read_only_tools"
    assert "blocked" in result["error"].lower()
