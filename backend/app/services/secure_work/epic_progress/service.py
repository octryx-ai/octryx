"""An Epic's progress: its stories and their sub-tasks, each in the lane its own events put it in."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem, WorkPullRequest
from ...workflow_runs.views import run_nodes
from .rules import ChildFacts, Lane, child_lane, rollup

PR_URL_FIELD = "pull_request_url"


async def epic_progress(db: AsyncSession, epic: WorkItem) -> dict[str, Any]:
    stories = await _items(db, epic.project_id, WorkItem.epic_key == epic.source_key)
    tasks = await _items(db, epic.project_id, WorkItem.parent_key.in_([story.source_key for story in stories])) \
        if stories else []
    children = [*stories, *tasks]
    runs = await _latest_runs(db, [item.id for item in children])
    prs = await _latest_prs(db, [item.id for item in children])
    phases = await _phase_titles(db, list(runs.values()))
    rows = {item.id: _row(item, runs.get(item.id), prs.get(item.id), phases) for item in children}
    by_story: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        by_story.setdefault(task.parent_key or "", []).append(rows[task.id])
    story_rows = []
    for story in stories:
        sub = by_story.get(story.source_key, [])
        story_rows.append({**rows[story.id], "tasks": sub,
                           "tasks_done": sum(1 for task in sub if task["lane"] == "done")})
    return {
        "epic": {"id": epic.id, "key": epic.source_key, "title": epic.title, "url": epic.source_url,
                 "work_state": epic.work_state, "source_status": epic.source_status},
        "summary": rollup([_lane_of(row) for row in story_rows]),
        "stories": story_rows,
    }


async def _items(db: AsyncSession, project_id: str | None, condition: Any) -> list[WorkItem]:
    return list((await db.execute(
        select(WorkItem).where(WorkItem.project_id == project_id, condition)
        .order_by(WorkItem.source_key.asc())
    )).scalars())


async def _latest_runs(db: AsyncSession, item_ids: list[str]) -> dict[str, WorkflowRun]:
    latest: dict[str, WorkflowRun] = {}
    if item_ids:
        for run in (await db.execute(select(WorkflowRun).where(WorkflowRun.work_item_id.in_(item_ids))
                                     .order_by(WorkflowRun.created_at.asc()))).scalars():
            latest[run.work_item_id] = run
    return latest


async def _latest_prs(db: AsyncSession, item_ids: list[str]) -> dict[str, WorkPullRequest]:
    latest: dict[str, WorkPullRequest] = {}
    if item_ids:
        for pr in (await db.execute(select(WorkPullRequest).where(WorkPullRequest.work_item_id.in_(item_ids))
                                    .order_by(WorkPullRequest.created_at.asc()))).scalars():
            latest[pr.work_item_id] = pr
    return latest


async def _phase_titles(db: AsyncSession, runs: list[WorkflowRun]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for run in runs:
        if run.current_node_id and run.flow_definition_version_id:
            node = next((n for n in await run_nodes(db, run) if n["id"] == run.current_node_id), None)
            if node and node.get("title"):
                titles[run.id] = str(node["title"])
    return titles


def _row(item: WorkItem, run: WorkflowRun | None, pr: WorkPullRequest | None, phases: dict[str, str]) -> dict[str, Any]:
    ci = ((run.context or {}).get("ci") or {}) if run is not None else {}
    run_pr = dict(run.pull_request or {}) if run is not None else {}
    facts = ChildFacts(
        work_state=item.work_state, run_status=run.status if run else None,
        run_phase=phases.get(run.id) if run else None, pr_status=pr.status if pr else None,
        build_status=pr.build_status if pr else None, ci_state=ci.get("state") if isinstance(ci, dict) else None,
    )
    lane = child_lane(facts)
    url = (pr.pr_url if pr else None) or run_pr.get("url") or (item.source_fields_json or {}).get(PR_URL_FIELD)
    return {
        "id": item.id, "key": item.source_key, "title": item.title, "issue_type": item.issue_type,
        "url": item.source_url, "work_state": item.work_state, "source_status": item.source_status,
        **lane.to_payload(),
        "run": {"id": run.id, "status": run.status, "phase": facts.run_phase} if run else None,
        "pull_request": {"url": url, "status": pr.status if pr else None} if url else None,
    }


def _lane_of(row: dict[str, Any]) -> Lane:
    return Lane(row["lane"], row["reason"], row["checks"], row["needs_you"])
