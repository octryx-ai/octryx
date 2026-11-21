"""Connector policy persistence helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorPolicy
from .normalization import normalize_connector_policy


async def list_connector_policies(
    db: AsyncSession,
    project_id: str | None = None,
) -> list[ConnectorPolicy]:
    stmt = select(ConnectorPolicy).order_by(ConnectorPolicy.connector_name.asc())
    if project_id is None:
        stmt = stmt.where(ConnectorPolicy.project_id.is_(None))
    else:
        stmt = stmt.where(ConnectorPolicy.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_connector_policy(
    db: AsyncSession,
    connector_name: str,
    project_id: str | None = None,
) -> ConnectorPolicy | None:
    stmt = select(ConnectorPolicy).where(ConnectorPolicy.connector_name == connector_name)
    if project_id is None:
        stmt = stmt.where(ConnectorPolicy.project_id.is_(None))
    else:
        stmt = stmt.where(ConnectorPolicy.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_connector_policy(
    db: AsyncSession,
    *,
    connector_name: str,
    project_id: str | None,
    policy: dict[str, Any],
    description: str = "",
    is_active: bool = True,
) -> ConnectorPolicy:
    entry = await get_connector_policy(db, connector_name, project_id)
    if not entry:
        entry = ConnectorPolicy(connector_name=connector_name, project_id=project_id)
        db.add(entry)
    entry.policy = normalize_connector_policy(policy)
    entry.description = description.strip() or None
    entry.is_active = is_active
    await db.flush()
    return entry
