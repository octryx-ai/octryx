"""Agent-group serialization helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect

from ...models import AgentGroup


def serialize_agent_group(group: AgentGroup) -> dict[str, Any]:
    state = sqlalchemy_inspect(group)
    agent_count = 0
    if "agents" not in state.unloaded:
        agent_count = len(group.agents or [])
    return {
        "id": group.id,
        "name": group.name,
        "slug": group.slug,
        "description": group.description or "",
        "category": group.category or "general",
        "projectId": group.project_id or "",
        "position": int(group.position or 100),
        "isActive": bool(group.is_active),
        "agentCount": agent_count,
    }
