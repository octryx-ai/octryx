from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemChangeUnit, WorkPullRequest
from ..workflow_runs.documentation.page import documentation_pages
from .coding.coding_agent_sessions import list_work_item_agent_sessions
from .plan_serializers import serialize_change_unit
from .pull_requests.record_identity import in_item_workspace
from .serializers import serialize_pull_request, serialize_work_item


async def get_work_item_lifecycle(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")

    units = list(
        (
            await db.execute(
                select(WorkItemChangeUnit)
                .where(WorkItemChangeUnit.work_item_id == item.id)
                .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
            )
        ).scalars()
    )
    pull_requests = list(
        (
            await db.execute(
                select(WorkPullRequest)
                .where(WorkPullRequest.work_item_id == item.id, in_item_workspace())
                .order_by(WorkPullRequest.source_updated_at.desc().nullslast(), WorkPullRequest.updated_at.desc())
            )
        ).scalars()
    )
    agent_sessions = await list_work_item_agent_sessions(db, item.id)
    active_session = agent_sessions[0] if agent_sessions else None
    return {
        "work_item": serialize_work_item(item),
        "links": {
            "work_url": f"/chat?area=work&work_item_id={item.id}",
            "coding_url": f"/chat?area=coding&work_item_id={item.id}",
            "jira_url": item.source_url,
            "active_chat_url": active_session["chat_url"] if active_session else None,
        },
        "agent_sessions": agent_sessions,
        "active_agent_session": active_session,
        "branches": [_branch_entry(unit, pull_requests) for unit in units],
        "pull_requests": [serialize_pull_request(row) for row in pull_requests],
        "change_units": [serialize_change_unit(unit) for unit in units],
        # The documentation pages workflow runs published for the item (Workflow B's documentation phase).
        "documentation_pages": await documentation_pages(db, item.id),
    }

def _branch_entry(unit: WorkItemChangeUnit, pull_requests: list[WorkPullRequest]) -> dict[str, Any]:
    pull_request = _matching_pull_request(unit, pull_requests)
    return {
        "change_unit_id": unit.id,
        "repository_name": unit.repository_name,
        "branch_name": unit.branch_name,
        "status": unit.status,
        "repository_url": pull_request.repository_url if pull_request else None,
        "branch_url": _branch_url(pull_request.repository_url, unit.branch_name) if pull_request else None,
        "pull_request_id": pull_request.id if pull_request else None,
        "pull_request_url": pull_request.pr_url if pull_request else unit.pr_link,
    }


def _matching_pull_request(unit: WorkItemChangeUnit, pull_requests: list[WorkPullRequest]) -> WorkPullRequest | None:
    return (
        next((row for row in pull_requests if row.change_unit_id == unit.id), None)
        or next((row for row in pull_requests if row.repository_slug == unit.repository_name), None)
        or None
    )


def _branch_url(repository_url: str | None, branch_name: str | None) -> str | None:
    if not repository_url or not branch_name:
        return None
    base = repository_url.rstrip("/")
    return f"{base}/browse?at=refs/heads/{branch_name}"
