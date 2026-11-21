"""``denied: workflow_archived`` for a phased workflow an admin archived or switched off.

A key that names no published workflow but an archived or inactive phased flow is refused as archived, never
answered ``unknown_key``: the caller learns the workflow exists and does not run now.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition
from .denials import MESSAGES, WORKFLOW_ARCHIVED


async def is_archived_workflow_key(db: AsyncSession, key: str, *, project_id: str | None = None) -> bool:
    normalized = str(key or "").strip()
    if not normalized:
        return False
    scope = (or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id) if project_id
             else FlowDefinition.project_id.is_(None))
    flow = (await db.execute(select(FlowDefinition.id).where(
        FlowDefinition.key == normalized, scope,
        or_(FlowDefinition.status == "archived", FlowDefinition.is_active.is_(False))).limit(1))).first()
    return flow is not None


def archived_workflow_resolution(base: dict[str, Any], workflow_key: str) -> dict[str, Any]:
    """The explicit selection's answer for an archived key (the execution profile maps it to ``denied``)."""
    return {**base, "status": WORKFLOW_ARCHIVED, "workflow_key": workflow_key,
            "unmatched_reason": MESSAGES[WORKFLOW_ARCHIVED], "denial": WORKFLOW_ARCHIVED}
