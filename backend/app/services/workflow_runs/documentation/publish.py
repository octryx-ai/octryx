"""Where a published documentation page is recorded: on the run and on the Work item."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkItemDocument
from ..records import record_event
from .target import PROVIDER

DOCUMENTATION_KEY = "documentation"
EVENT_PUBLISHED = "documentation_published"


async def _record(db: AsyncSession, run: WorkflowRun, page: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), DOCUMENTATION_KEY: page}
    if run.work_item_id:
        row = (await db.execute(select(WorkItemDocument).where(
            WorkItemDocument.work_item_id == run.work_item_id, WorkItemDocument.provider == PROVIDER,
            WorkItemDocument.connection_id == page["connection_id"],
            WorkItemDocument.instance_url == page["instance"],
            WorkItemDocument.page_id == page["page_id"]))).scalar_one_or_none()
        if row is None:
            row = WorkItemDocument(work_item_id=run.work_item_id, project_id=run.project_id, provider=PROVIDER,
                                   connection_id=page["connection_id"], instance_url=page["instance"],
                                   space_key=page["space_key"], page_id=page["page_id"], title=page["title"])
            db.add(row)
        row.title, row.url, row.version, row.run_id = page["title"], page["url"], page["version"], run.id
        await db.flush()
    record_event(db, run, EVENT_PUBLISHED, node_id=run.current_node_id, detail={
        key: page[key] for key in ("page_id", "space_key", "version", "url", "status")})


__all__ = ["DOCUMENTATION_KEY"]
