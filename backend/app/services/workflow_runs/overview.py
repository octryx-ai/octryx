"""The Workflows page: every phased workflow and flow graph with class, scope, use, status and last change."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from .overview_changes import author_names
from .overview_flows import flow_rows, load_flows

USAGE_WINDOW_DAYS = 30


async def workflows_overview(
    db: AsyncSession, *, project_id: str | None = None, include_inactive: bool = False
) -> dict[str, Any]:
    flows = await load_flows(db, project_id=project_id, include_inactive=include_inactive)
    project_ids = {flow.project_id for flow in flows if flow.project_id}
    names = (
        dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all())
        if project_ids
        else {}
    )
    authors = await author_names(db, flows)
    rows = await flow_rows(db, flows, names=names, window_days=USAGE_WINDOW_DAYS, authors=authors)
    return {"flows": rows, "usage_window_days": USAGE_WINDOW_DAYS}


__all__ = ["USAGE_WINDOW_DAYS", "workflows_overview"]
