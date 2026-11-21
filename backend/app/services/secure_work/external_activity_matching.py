"""Which Work Items an external connector event belongs to: by source reference, pull request or change unit."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    ConnectorWatcher,
    ConnectorWatcherEvent,
    WorkItem,
    WorkItemChangeUnit,
    WorkPullRequest,
)
from .external_activity_values import MAX_CANDIDATE_ITEMS, _list, _string, _string_set, _unique
from .jira_values import object_value
from .plans.redeclare import SUPERSEDED_UNIT_STATUS
from .pull_requests.record_identity import in_item_workspace


async def _matching_work_items(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    event: ConnectorWatcherEvent,
    source_payload: dict[str, Any],
) -> list[tuple[WorkItem, list[str], list[WorkItemChangeUnit]]]:
    candidates = await _candidate_work_items(db, watcher=watcher, source_payload=source_payload)
    units = await _candidate_change_units(db, candidates)
    pull_requests = await _candidate_pull_requests(db, candidates)
    results: list[tuple[WorkItem, list[str], list[WorkItemChangeUnit]]] = []
    for item in candidates:
        item_prs = [row for row in pull_requests if row.work_item_id == item.id]
        matched_by = _matched_by(item, event=event, source_payload=source_payload, pull_requests=item_prs)
        item_units = [unit for unit in units if unit.work_item_id == item.id]
        unit_matches = [
            unit for unit in item_units
            if _change_unit_matches(unit, source_payload=source_payload,
                                    pull_requests=[row for row in item_prs if row.change_unit_id == unit.id])
        ]
        if unit_matches:
            matched_by.append("change_unit")
        if matched_by:
            results.append((item, matched_by, unit_matches))
    return results


async def _candidate_work_items(
    db: AsyncSession,
    *,
    watcher: ConnectorWatcher,
    source_payload: dict[str, Any],
) -> list[WorkItem]:
    keys = _string_set(source_payload.get("work_item_keys"))
    stmt = select(WorkItem)
    if watcher.project_id:
        stmt = stmt.where(WorkItem.project_id == watcher.project_id)
    if keys:
        stmt = stmt.where(WorkItem.source_key.in_(sorted(keys)))
    stmt = stmt.order_by(WorkItem.updated_at.desc()).limit(MAX_CANDIDATE_ITEMS)
    rows = (await db.execute(stmt)).scalars().all()
    if rows or not keys:
        return rows
    fallback = select(WorkItem)
    if watcher.project_id:
        fallback = fallback.where(WorkItem.project_id == watcher.project_id)
    fallback = fallback.order_by(WorkItem.updated_at.desc()).limit(MAX_CANDIDATE_ITEMS)
    return (await db.execute(fallback)).scalars().all()


async def _candidate_change_units(db: AsyncSession, items: list[WorkItem]) -> list[WorkItemChangeUnit]:
    if not items:
        return []
    ids = [item.id for item in items]
    stmt = select(WorkItemChangeUnit).where(
        WorkItemChangeUnit.work_item_id.in_(ids),
        WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
    )
    return (await db.execute(stmt)).scalars().all()


async def _candidate_pull_requests(db: AsyncSession, items: list[WorkItem]) -> list[WorkPullRequest]:
    """D12: the candidates' pull requests from work_pull_requests, the one PR source."""
    if not items:
        return []
    stmt = select(WorkPullRequest).where(WorkPullRequest.work_item_id.in_([item.id for item in items]),
                                         in_item_workspace())
    return list((await db.execute(stmt)).scalars().all())


def _recorded_pr_values(pull_requests: list[WorkPullRequest]) -> set[str]:
    values: set[str] = set()
    for row in pull_requests:
        for value in (row.pr_id, row.pr_key):
            if _string(value):
                values.update({str(value), f"pr:{value}"})
        if _string(row.pr_url):
            values.add(str(row.pr_url))
    return values


def _matched_by(
    item: WorkItem,
    *,
    event: ConnectorWatcherEvent,
    source_payload: dict[str, Any],
    pull_requests: list[WorkPullRequest] | None = None,
) -> list[str]:
    source_fields = object_value(item.source_fields_json)
    matched: list[str] = []
    if item.source_key in _string_set(source_payload.get("work_item_keys")):
        matched.append("work_item_key")
    issue = object_value(source_payload.get("issue"))
    if issue.get("key") and item.source_key == issue.get("key"):
        matched.append("jira_issue")
    branch = _string(source_payload.get("branch"))
    if branch and branch in _string_set(source_fields.get("planned_branches")):
        matched.append("planned_branch")
    repository = object_value(source_payload.get("repository"))
    repo_values = _string_set(source_fields.get("affected_repositories")) | _string_set(
        source_fields.get("repositories")
    )
    if repository.get("slug") in repo_values or repository.get("name") in repo_values:
        matched.append("repository")
    pr = object_value(source_payload.get("pull_request"))
    # The item's recorded pull requests (``WorkItemPullRequest``).
    pr_values = _recorded_pr_values(pull_requests or [])
    if pr.get("id") and f"pr:{pr['id']}" in pr_values:
        matched.append("pull_request")
    if pr.get("url") and pr.get("url") in pr_values:
        matched.append("pull_request")
    external_id = _string(event.external_id)
    if external_id and external_id in pr_values:
        matched.append("pull_request")
    page = object_value(source_payload.get("page"))
    if _source_ref_matches(source_fields, values=[page.get("id"), page.get("title"), page.get("url")]):
        matched.append("source_reference")
    document = object_value(source_payload.get("document"))
    if _source_ref_matches(source_fields, values=[document.get("key"), document.get("source"), document.get("title")]):
        matched.append("source_reference")
    return _unique(matched)


def _change_unit_matches(
    unit: WorkItemChangeUnit, *, source_payload: dict[str, Any], pull_requests: list[WorkPullRequest] | None = None
) -> bool:
    repository = object_value(source_payload.get("repository"))
    branch = _string(source_payload.get("branch"))
    pr = object_value(source_payload.get("pull_request"))
    recorded = _recorded_pr_values(pull_requests or [])
    if (pr.get("url") and pr.get("url") in recorded) or (pr.get("id") and f"pr:{pr['id']}" in recorded):
        return True
    if branch and unit.branch_name == branch:
        return True
    if repository.get("slug") and unit.repository_name == repository.get("slug"):
        return True
    if repository.get("name") and unit.repository_name == repository.get("name"):
        return True
    if pr.get("url") and unit.pr_link == pr.get("url"):
        return True
    if pr.get("id") and unit.pr_link and str(pr.get("id")) in unit.pr_link:
        return True
    return False


def _source_ref_matches(source_fields: dict[str, Any], *, values: list[Any]) -> bool:
    references = set()
    for key in ("source_references", "knowledge_sources", "confluence_pages", "source_evidence"):
        references.update(_flatten_reference_values(source_fields.get(key)))
    return any(_string(value) in references for value in values if _string(value))


def _flatten_reference_values(value: Any) -> set[str]:
    values: set[str] = set()
    for item in _list(value):
        if isinstance(item, dict):
            for current in item.values():
                if _string(current):
                    values.add(str(current))
        elif _string(item):
            values.add(str(item))
    return values
