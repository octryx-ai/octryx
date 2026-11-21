"""SLA wrappers used by admin task service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...sla import (
    create_sla_definition,
    delete_sla_definition,
    list_sla_breaches,
    list_sla_definitions,
    update_sla_definition,
)


async def list_task_sla_definitions_for_admin(db: AsyncSession) -> list[dict[str, Any]]:
    return await list_sla_definitions(db)


async def create_task_sla_definition_for_admin(db: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    return await create_sla_definition(db, payload=payload)


async def update_task_sla_definition_for_admin(
    db: AsyncSession,
    *,
    definition_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return await update_sla_definition(db, definition_id=definition_id, payload=payload)


async def delete_task_sla_definition_for_admin(db: AsyncSession, *, definition_id: str) -> dict[str, Any]:
    return await delete_sla_definition(db, definition_id=definition_id)


async def list_task_sla_breaches_for_admin(
    db: AsyncSession,
    *,
    limit: int = 100,
    unresolved_only: bool = False,
) -> list[dict[str, Any]]:
    return await list_sla_breaches(db, limit=limit, unresolved_only=unresolved_only)
