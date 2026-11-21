"""Shared helpers for the test_governed_default_tool_sets_* modules."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.agent.core.context.run_context import prepare_agent_run
from app.agent.engine.messages._engine_message_helpers import _exclude_tool_definitions, _filter_tool_definitions
from app.models import Project, Session, User


def _definition(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}


async def _prepare(db, tmp_path: Path, project: Project, admin: User, agent_type: str, agent_definition=None):
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type=agent_type)
    db.add(session)
    await db.commit()
    return await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message="Check the latest Jira ticket for acme-orders and summarize it.",
        user_id=admin.id,
        project_id=project.id,
        agent_type=agent_type,
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=agent_definition,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=_filter_tool_definitions,
        exclude_tool_definitions=_exclude_tool_definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )
