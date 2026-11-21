"""Discovery for the setup drawer (intake redesign §3.2–3.3): what a Workspace connection offers an intake.

Each source answers for itself (``intake/registry``): Jira lists projects, issue types, statuses and the fields an
intake maps by plain name (``jira_discovery``); ServiceNow its tables, default open-state filter and mapping and the
groups and services seen in recent records. The Work states every mapping may target are the shared workflow
vocabulary. The connection is checked first, so an unknown one never reaches a source.
"""

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
