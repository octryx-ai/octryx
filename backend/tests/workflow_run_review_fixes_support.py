"""Shared helpers for the test_workflow_run_review_fixes_* modules."""

from __future__ import annotations

import uuid

from app.models import Project
from app.models.runtime.secure_work import WorkItem


async def _item(db, project: Project | None, **fields) -> WorkItem:
    item = WorkItem(source_type="jira", source_instance="test", source_key=f"RV-{uuid.uuid4().hex[:6]}",
                    title="Totals are wrong", project_id=project.id if project else None, **fields)
    db.add(item)
    await db.flush()
    return item
