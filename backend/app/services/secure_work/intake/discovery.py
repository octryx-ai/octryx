"""Discovery for the setup drawer: what a Workspace connection offers an intake. Each source answers for itself; the
connection is checked first, so an unknown one never reaches a source."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..workflow_mapping import DEFAULT_WORKFLOW_STATES
from .registry import require_source

WORK_STATES = [{"key": state["key"], "label": state["label"]} for state in DEFAULT_WORKFLOW_STATES]


async def discover(db: AsyncSession, project_id: str, source_type: str, connection_id: str) -> dict[str, Any]:
    source = require_source(source_type)
    await source.require_connection(db, project_id, connection_id)
    return await source.discover(db, project_id, connection_id)


async def count(db: AsyncSession, project_id: str, source_type: str, connection_id: str,
                what: dict[str, Any]) -> dict[str, Any]:
    source = require_source(source_type)
    await source.require_connection(db, project_id, connection_id)
    return await source.count(db, project_id, connection_id, what)


__all__ = ["WORK_STATES", "count", "discover"]
