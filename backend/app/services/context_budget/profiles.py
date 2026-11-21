"""Stored context budget profiles: defaults, listing, upsert and delete."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ContextBudgetProfile

# Triggers match only the explicit haystack tokens (route reason, tier, agent type, capability,
# the ``subagent`` flag); the prompt text is not part of it.
DEFAULT_CONTEXT_BUDGET_PROFILES: list[dict[str, Any]] = [
    {
        "name": "Sub-Agent Focused",
        "trigger_pattern": r"\bsubagent\b",
        "base_budget": 5600,
        "tool_budget": 700,
        "history_budget": 200,
        "entity_budget": 350,
        "memory_budget": 350,
        "priority": 450,
    },
    {
        "name": "Change Worker",
        "trigger_pattern": r"\bchange_or_continuation\b",
        "base_budget": 9000,
        "tool_budget": 1400,
        "history_budget": 450,
        "entity_budget": 500,
        "memory_budget": 500,
        "priority": 250,
    },
    {
        "name": "Admin Control Plane",
        "trigger_pattern": r"\badmin\b|\badmin_capability\b",
        "base_budget": 18000,
        "tool_budget": 2400,
        "history_budget": 600,
        "entity_budget": 600,
        "memory_budget": 600,
        "priority": 260,
    },
    {
        "name": "Contextual Standard",
        "trigger_pattern": r"\b(contextual_request|default_standard)\b",
        "base_budget": 5000,
        "tool_budget": 700,
        "history_budget": 300,
        "entity_budget": 300,
        "memory_budget": 250,
        "priority": 100,
    },
]


def serialize_context_budget_profile(row: ContextBudgetProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "trigger_pattern": row.trigger_pattern,
        "base_budget": int(row.base_budget or 0),
        "tool_budget": int(row.tool_budget or 0),
        "history_budget": int(row.history_budget or 0),
        "entity_budget": int(row.entity_budget or 0),
        "memory_budget": int(row.memory_budget or 0),
        "priority": int(row.priority or 0),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_default_context_budget_profiles(db: AsyncSession) -> None:
    existing = (await db.execute(select(ContextBudgetProfile.id).limit(1))).scalar_one_or_none()
    if existing:
        return
    for payload in DEFAULT_CONTEXT_BUDGET_PROFILES:
        db.add(
            ContextBudgetProfile(
                id=str(uuid.uuid4()),
                name=str(payload["name"]),
                trigger_pattern=str(payload["trigger_pattern"]),
                base_budget=int(payload["base_budget"]),
                tool_budget=int(payload["tool_budget"]),
                history_budget=int(payload["history_budget"]),
                entity_budget=int(payload["entity_budget"]),
                memory_budget=int(payload["memory_budget"]),
                priority=int(payload["priority"]),
                is_active=True,
            )
        )
    await db.flush()


async def list_context_budget_profiles(db: AsyncSession) -> list[dict[str, Any]]:
    await ensure_default_context_budget_profiles(db)
    rows = (
        (
            await db.execute(
                select(ContextBudgetProfile).order_by(
                    ContextBudgetProfile.priority.desc(), ContextBudgetProfile.name.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [serialize_context_budget_profile(row) for row in rows]


async def upsert_context_budget_profile(
    db: AsyncSession,
    *,
    profile_id: str | None,
    name: str,
    trigger_pattern: str,
    base_budget: int,
    tool_budget: int,
    history_budget: int,
    entity_budget: int,
    memory_budget: int,
    priority: int = 100,
    is_active: bool = True,
) -> dict[str, Any]:
    normalized_name = str(name or "").strip()
    normalized_pattern = str(trigger_pattern or "").strip()
    if not normalized_name:
        raise ValueError("name is required")
    if not normalized_pattern:
        raise ValueError("trigger_pattern is required")
    try:
        re.compile(normalized_pattern)
    except re.error as exc:
        raise ValueError(f"Invalid trigger_pattern: {exc}") from exc

    row = None
    if profile_id:
        row = await db.get(ContextBudgetProfile, str(profile_id))
    if row is None:
        row = ContextBudgetProfile(id=str(uuid.uuid4()))
        db.add(row)
    row.name = normalized_name
    row.trigger_pattern = normalized_pattern
    row.base_budget = max(0, int(base_budget or 0))
    row.tool_budget = max(0, int(tool_budget or 0))
    row.history_budget = max(0, int(history_budget or 0))
    row.entity_budget = max(0, int(entity_budget or 0))
    row.memory_budget = max(0, int(memory_budget or 0))
    row.priority = int(priority or 0)
    row.is_active = bool(is_active)
    await db.commit()
    await db.refresh(row)
    return serialize_context_budget_profile(row)


async def delete_context_budget_profile(db: AsyncSession, *, profile_id: str) -> None:
    row = await db.get(ContextBudgetProfile, str(profile_id))
    if row is None:
        return
    await db.delete(row)
    await db.commit()
