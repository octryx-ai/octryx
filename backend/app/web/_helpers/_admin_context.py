"""Admin page context builders for the settings and agents pages."""

# ruff: noqa: E501, I001

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Message,
    Project,
    Session as AgentSession,
    User,
)
from ...services.agent_mode import list_agent_modes, serialize_agent_mode


def _tool_options() -> list[str]:
    from app.services.agent_definition_validation_steps import known_tool_names

    return sorted(known_tool_names())

__all__ = [
    "_build_settings_context",
    "_build_agents_context",
]


async def _build_settings_context(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
) -> dict:
    from app.services.runtime_options import list_chat_runtime_options

    runtime_options = await list_chat_runtime_options(db)
    runtime_label_by_id = {option["value"]: option["label"] for option in runtime_options}
    automatic_runtime_label = runtime_label_by_id.get("", "Automatic fallback chain")

    sessions = (
        (
            await db.execute(
                select(AgentSession)
                .where(AgentSession.user_id == user.id, AgentSession.status == "archived")
                .order_by(AgentSession.started_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    archived_threads = []
    for session in sessions:
        messages = (
            (
                await db.execute(
                    select(Message).where(Message.session_id == session.id).order_by(Message.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        first_user_message = next((msg for msg in messages if msg.role == "user" and msg.content), None)
        last_message = messages[-1] if messages else None
        project = await db.get(Project, session.project_id) if session.project_id else None
        archived_threads.append(
            {
                "id": session.id,
                "title": (session.metadata_ or {}).get("title")
                or (
                    first_user_message.content[:72]
                    if first_user_message and first_user_message.content
                    else "Archived thread"
                ),
                "preview": (last_message.content[:140] if last_message and last_message.content else ""),
                "message_count": len(messages),
                "project_name": project.name if project else "No project",
                "runtime_label": (session.metadata_ or {}).get("runtime_label") or automatic_runtime_label,
                "started_at": session.started_at,
            }
        )

    return {
        "request": request,
        "user": user,
        "archived_threads": archived_threads,
    }


async def _build_agents_context(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    agent_id: str | None = None,
    new_agent: bool = False,
) -> dict:
    from .control_plane import _list_agent_definitions
    from app.services.runtime_options import list_chat_runtime_options
    from app.services.agent_definition_payload import serialize_agent_definition_payload
    from .auth import THINKING_LEVELS

    agents = await _list_agent_definitions(db, user_id=user.id)
    runtime_options = await list_chat_runtime_options(db)
    projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    agent_modes = [serialize_agent_mode(mode) for mode in list_agent_modes()]

    selected_agent = None
    if agent_id and not new_agent:
        selected_agent = next((agent for agent in agents if agent.id == agent_id), None)
    if not selected_agent and agents and not new_agent:
        selected_agent = agents[0]

    return {
        "request": request,
        "user": user,
        "agents": [serialize_agent_definition_payload(agent) for agent in agents],
        "selected_agent": serialize_agent_definition_payload(selected_agent) if selected_agent else None,
        "projects": projects,
        "runtime_options": runtime_options,
        "thinking_levels": THINKING_LEVELS,
        "agent_type_options": [str(mode["key"]) for mode in agent_modes],
        "agent_modes": agent_modes,
        "step_type_options": [
            "analysis",
            "tooling",
            "documentation",
            "change",
            "knowledge",
            "tdd_cycle",
            "self_review",
            "handover",
        ],
        "tool_options": _tool_options(),
        "new_agent": new_agent,
    }
