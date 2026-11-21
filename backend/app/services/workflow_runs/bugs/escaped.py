"""An escaped defect: a bug in work the platform delivered (maintenance metrics).

At the bug flow's intake the platform looks for the work item the bug is about: the report's linked issues (a Jira
link's key), its parent, or a work item key the report names (````). When one of them was delivered by a
completed platform run of another workflow than this bug flow's, the run records ``bug_escaped_from`` with that key
and the delivering workflow; ``octryx_item_escaped_defects_total`` counts the event (never a query at metric time).
Revert pull requests as a second source follow later.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..records import record_event

EVENT_ESCAPED = "bug_escaped_from"
_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b")
MAX_CANDIDATES = 10


def candidate_keys(item: WorkItem) -> list[str]:
    """The keys the bug points at: linked issues, the parent, then keys its text names (not its own)."""
    from ...secure_work.jira.jira_scope import _linked_key

    keys = [_linked_key(link) for link in item.linked_issues_json or [] if isinstance(link, dict)]
    keys += [str(item.parent_key or "")]
    keys += _KEY.findall(f"{item.title}\n{item.description or ''}")
    own = str(item.source_key or "")
    return [key for key in dict.fromkeys(keys) if key and key != own][:MAX_CANDIDATES]


async def record_escape(db: AsyncSession, run: WorkflowRun, item: WorkItem | None) -> dict[str, Any] | None:
    """Record the work item this bug escaped from, once per run; ``None`` when none is known."""
    if item is None or dict(run.context or {}).get("bug_escaped_from"):
        return None
    keys = candidate_keys(item)
    if not keys:
        return None
    rows = (await db.execute(
        select(WorkItem.source_key, WorkflowRun.workflow_key)
        .join(WorkflowRun, WorkflowRun.work_item_id == WorkItem.id)
        .where(WorkItem.project_id == item.project_id, WorkItem.source_key.in_(keys),
               WorkflowRun.status == "completed", WorkflowRun.workflow_key != run.workflow_key)
    )).all()
    delivered = {str(row.source_key): str(row.workflow_key) for row in rows}
    key = next((key for key in keys if key in delivered), None)
    if key is None:
        return None
    escaped = {"key": key, "origin_workflow": delivered[key]}
    run.context = {**dict(run.context or {}), "bug_escaped_from": escaped}
    record_event(db, run, EVENT_ESCAPED, node_id=run.current_node_id, detail=escaped)
    return escaped


__all__ = ["EVENT_ESCAPED", "candidate_keys", "record_escape"]
