"""Shared helpers for admin management tools."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext


def _require_admin(context: ToolContext) -> str | None:
    """Return error string if user is not admin, else None."""
    if "admin" not in (context.roles or []):
        return "Access denied: admin role required."
    return None


def _require_admin_or_operator(context: ToolContext) -> str | None:
    if not ({"admin", "operator"} & set(context.roles or [])):
        return "Access denied: admin or operator role required."
    return None


async def _resolve_project_id(context: ToolContext, project_ref: Any | None) -> tuple[str | None, str | None]:
    if project_ref in (None, ""):
        return None, None
    if not context.db:
        return None, "No database connection"
    from sqlalchemy import select

    from ...models import Project

    ref = str(project_ref).strip()
    result = await context.db.execute(select(Project).where((Project.id == ref) | (Project.name == ref)))
    project = result.scalar_one_or_none()
    from ...services.project.private_workspace import private_role  # noqa: PLC0415

    # Review: somebody else's private Workspace does not exist for the admin tools.
    if not project or (project.access_mode == "private" and private_role(project, str(context.user_id)) is None):
        return None, f"Project '{ref}' not found"
    return str(project.id), None


async def _resolve_channel(context: ToolContext, channel_ref: Any | None):
    if not channel_ref:
        return None, "channel_id or channel_name is required"
    if not context.db:
        return None, "No database connection"
    from sqlalchemy import String, cast, select

    from ...models import ChannelConfig

    ref = str(channel_ref).strip()
    result = await context.db.execute(
        select(ChannelConfig).where((cast(ChannelConfig.id, String) == ref) | (ChannelConfig.name == ref))
    )
    channel = result.scalar_one_or_none()
    if not channel:
        return None, f"Channel '{ref}' not found"
    return channel, None


async def _resolve_task(context: ToolContext, task_ref: Any | None):
    if not task_ref:
        return None, "task_id or task_name is required"
    if not context.db:
        return None, "No database connection"
    from sqlalchemy import select

    from ...models import Task

    ref = str(task_ref).strip()
    result = await context.db.execute(select(Task).where((Task.id == ref) | (Task.name == ref)))
    task = result.scalar_one_or_none()
    if not task:
        return None, f"Task '{ref}' not found"
    return task, None


async def _resolve_agent_definition(context: ToolContext, agent_ref: Any | None):
    if not agent_ref:
        return None, "agent_id or name is required"
    if not context.db:
        return None, "No database connection"
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ...models import AgentDefinition

    ref = str(agent_ref).strip()
    result = await context.db.execute(
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps))
        .where((AgentDefinition.id == ref) | (AgentDefinition.name == ref))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return None, f"Agent '{ref}' not found"
    return agent, None


__all__ = [
    "_require_admin",
    "_require_admin_or_operator",
    "_resolve_agent_definition",
    "_resolve_channel",
    "_resolve_project_id",
    "_resolve_task",
]
