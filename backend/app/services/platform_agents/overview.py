"""The Agents page's platform agents: the three rows with their shipped role, never code-only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition
from .catalog import PLATFORM_AGENT_KEYS


async def platform_agents_overview(db: AsyncSession) -> list[dict[str, Any]]:
    rows = {row.builtin_key: row for row in (await db.execute(
        select(AgentDefinition).where(AgentDefinition.builtin_key.in_(PLATFORM_AGENT_KEYS)))).scalars()}
    return [
        {"key": key, "id": row.id, "name": row.name, "description": row.description or "",
         "capability_ceiling": row.capability_ceiling, "runtime_preference": row.runtime_preference or "",
         "chat_selectable": bool(row.chat_selectable),
         "default_workflow_key": "", "row": True}
        for key in PLATFORM_AGENT_KEYS if (row := rows.get(key)) is not None
    ]
