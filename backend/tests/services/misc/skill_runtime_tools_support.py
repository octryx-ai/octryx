"""Shared helpers for the test_skill_runtime_tools_* modules."""

from __future__ import annotations

import uuid

from app.models import User
from app.tools.context import ToolContext


def _tool_context(
    *,
    db,
    user: User,
    roles: list[str] | None = None,
    project_id: str | None = None,
    tool_names: list[str] | None = None,
) -> ToolContext:
    return ToolContext(
        user_id=user.id,
        project_ids=[project_id] if project_id else [],
        roles=roles or ["admin"],
        session_id=str(uuid.uuid4()),
        project_config={"project_id": project_id} if project_id else {},
        current_user_message="daily summary",
        db=db,
        turn_context_snapshot={"tool_names": tool_names or ["skill_search", "skill_get", "read_workspace_file"]},
    )
