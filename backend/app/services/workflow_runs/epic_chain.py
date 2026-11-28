"""An epic works through its stories by itself."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .records import WorkflowRunError, record_event
from .states import ACTIVE_STATUSES

logger = logging.getLogger(__name__)

STORY_WORKFLOW = "epic-delivery"
STORY_WORKFLOWS = frozenset({"epic-delivery", "team-delivery"})
STORY_WORKFLOW_KEY = "story_workflow"
SPEC_WORKFLOW = "spec-writing"
STORIES_KEY = "stories"
BASE_BRANCH_KEY = "base_branch"
CHAIN_KEY = "epic_chain"
EVENT_NEXT_STORY = "epic_next_story"
EVENT_CHAIN_FAILED = "epic_chain_failed"


async def _epic_key(db: AsyncSession, run: WorkflowRun) -> tuple[str, WorkItem | None]:
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return "", None
    if _is_epic_run(run) and str(item.issue_type or "").lower() == "epic":
        return str(item.source_key or ""), item
    if _builds_stories(run.workflow_key) and item.epic_key:
        return str(item.epic_key), item
    return "", item


def _is_epic_run(run: WorkflowRun) -> bool:
    return run.workflow_key == SPEC_WORKFLOW or isinstance(dict(run.context or {}).get(STORIES_KEY), list)


def story_order(run: WorkflowRun) -> list[str]:
    context = dict(run.context or {})
    stored = context.get(STORIES_KEY) if _is_epic_run(run) else dict(context.get(CHAIN_KEY) or {}).get(STORIES_KEY)
    return [str(key) for key in stored or [] if str(key or "").strip()] if isinstance(stored, list) else []


def _builds_stories(workflow_key: str | None) -> bool:
    return workflow_key in STORY_WORKFLOWS or workflow_key == STORY_WORKFLOW


def story_workflow(run: WorkflowRun) -> str:
    # A choice that is no story workflow is returned as is, so continue_epic refuses it on record instead of defaulting.
    if not _is_epic_run(run):
        chosen = str(run.workflow_key)
    else:
        chosen = str(dict(run.context or {}).get(STORY_WORKFLOW_KEY) or "").strip()
    return chosen or STORY_WORKFLOW


async def _stories(db: AsyncSession, project_id: str | None, epic_key: str,
                   order: list[str] | None = None) -> list[WorkItem]:
    stories = list((await db.execute(
        select(WorkItem).where(WorkItem.epic_key == epic_key, WorkItem.project_id == project_id)
        .order_by(WorkItem.created_at, WorkItem.source_key))).scalars().all())
    rank = {key: index for index, key in enumerate(order or [])}
    stories.sort(key=lambda story: rank.get(str(story.source_key), len(rank)))  # stable: the rest keeps its order
    return stories


async def next_story(db: AsyncSession, project_id: str | None, epic_key: str,
                     order: list[str] | None = None) -> WorkItem | None:
    # An aborted run does not count: it must not move the chain past its story.
    for story in await _stories(db, project_id, epic_key, order):
        settled = (await db.execute(select(WorkflowRun.id).where(
            WorkflowRun.work_item_id == story.id, WorkflowRun.parent_run_id.is_(None),
            or_(WorkflowRun.status.in_(tuple(ACTIVE_STATUSES)), WorkflowRun.outcome == "done"),
        ).limit(1))).scalar_one_or_none()
        if settled is None:
            return story
    return None


async def _last_done(db: AsyncSession, item_ids: list[str]) -> WorkflowRun | None:
    if not item_ids:
        return None
    return (await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id.in_(item_ids), WorkflowRun.parent_run_id.is_(None), WorkflowRun.outcome == "done",
        WorkflowRun.branch.is_not(None), WorkflowRun.branch != "",
    ).order_by(WorkflowRun.completed_at.desc().nulls_last(), WorkflowRun.created_at.desc()).limit(1)
    )).scalars().first()


async def story_start_context(db: AsyncSession, item: WorkItem | None, workflow_key: str,
                              context: dict[str, Any] | None) -> dict[str, Any] | None:
    context = dict(context or {})
    if item is None or not item.epic_key or not _builds_stories(workflow_key) or (
            context.get(BASE_BRANCH_KEY) or context.get(CHAIN_KEY)):
        return context or None
    epic_key = str(item.epic_key)
    epic_ids = list((await db.execute(select(WorkItem.id).where(
        WorkItem.source_key == epic_key, WorkItem.project_id == item.project_id))).scalars().all())
    epic_run = await _last_done(db, epic_ids)
    stories = await _stories(db, item.project_id, epic_key)
    order = story_order(epic_run) if epic_run is not None else []
    if not order:
        newest = await _last_done(db, [story.id for story in stories])
        order = story_order(newest) if newest is not None else []
    stories = await _stories(db, item.project_id, epic_key, order)
    own = str(item.source_key or "")
    after = None
    if own in order:
        keys = [str(story.source_key) for story in stories]
        for story in reversed(stories[:keys.index(own)]):
            after = await _last_done(db, [story.id])
            if after is not None:
                break
    else:
        after = await _last_done(db, [story.id for story in stories if story.id != item.id])
    after = after or epic_run
    if after is None:
        return context or None
    return {**context, BASE_BRANCH_KEY: after.branch,
            CHAIN_KEY: {"epic": epic_key, "after_run": after.id, "after_workflow": after.workflow_key,
                        "derived_at_start": True, **({STORIES_KEY: order} if order else {})}}


async def continue_epic(db: AsyncSession, run: WorkflowRun, *, actor_id: str | None) -> WorkflowRun | None:
    if run.outcome != "done" or run.parent_run_id:
        return None
    epic, _item = await _epic_key(db, run)
    if not epic:
        return None
    order = story_order(run)
    story = await next_story(db, run.project_id, epic, order)
    if story is None:
        _record(run, {"state": "finished", "epic": epic})
        return None
    from .records import new_chat_session, start_run
    from .triage_routing import _follow_up_target

    requester = await db.get(User, run.requested_by) if run.requested_by else None
    if requester is None or not requester.is_active:
        return _failed(db, run, epic, story, "requester_inactive", actor_id)
    target, _fallback = await _follow_up_target(db, run, requester)
    workflow = story_workflow(run)
    if not _builds_stories(workflow):
        return _failed(db, run, epic, story, "not_a_story_workflow", actor_id)
    context = {BASE_BRANCH_KEY: run.branch} if run.branch else {}
    context[CHAIN_KEY] = {"epic": epic, "after_run": run.id, "after_workflow": run.workflow_key,
                          **({STORIES_KEY: order} if order else {})}
    try:
        # No savepoint around the start: the story's first node (the branch) dispatches a
        # platform tool that commits, which closed the savepoint and left the run standing at its branch node. The
        # start runs like a person's start; refusals come before anything is written (WorkflowRunError).
        thread = await new_chat_session(db, requester, run.project_id)
        child = await start_run(db, user=requester, workflow_key=workflow, project_id=run.project_id,
                                work_item_id=story.id, repository=run.repository, session=thread,
                                context=context, runtime_target=target)
    except WorkflowRunError as error:
        return _failed(db, run, epic, story, error.code, actor_id)
    except Exception as error:  # noqa: BLE001 - the finished run stands; the failure is on record
        logger.exception("epic %s: next story %s could not start", epic, story.source_key)
        return _failed(db, run, epic, story, type(error).__name__, actor_id)
    _record(run, {"state": "started", "epic": epic, "story": story.source_key, "run_id": child.id,
                  "workflow": workflow})
    await _epic_in_progress(db, child, story, requester)
    record_event(db, run, EVENT_NEXT_STORY, node_id=run.current_node_id, actor_id=actor_id,
                 detail={"epic": epic, "story": story.source_key, "run_id": child.id, "base_branch": run.branch,
                         "workflow": workflow})
    return child


async def _epic_in_progress(db: AsyncSession, child: WorkflowRun, story: WorkItem, requester: User) -> None:
    from .platform.pr_work_state import epic_in_progress

    try:
        await epic_in_progress(db, child, story, requester)
    except Exception:  # noqa: BLE001 - a lifecycle move never stops the chain
        logger.exception("epic of %s: the move to development failed", story.source_key)


def _failed(db: AsyncSession, run: WorkflowRun, epic: str, story: WorkItem, code: str,
            actor_id: str | None) -> None:
    _record(run, {"state": "failed", "epic": epic, "story": story.source_key, "code": code})
    record_event(db, run, EVENT_CHAIN_FAILED, node_id=run.current_node_id, actor_id=actor_id,
                 detail={"epic": epic, "story": story.source_key, "code": code})
    return None


def _record(run: WorkflowRun, value: dict[str, Any]) -> None:
    # The build order stays: a retry without it would fall back to creation order.
    stories = dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get(STORIES_KEY)
    kept = {STORIES_KEY: stories} if isinstance(stories, list) and stories else {}
    run.context = {**dict(run.context or {}), CHAIN_KEY: {**kept, **value, "at": utc_now().isoformat()}}


__all__ = ["BASE_BRANCH_KEY", "CHAIN_KEY", "EVENT_NEXT_STORY", "STORIES_KEY", "STORY_WORKFLOWS", "continue_epic",
           "next_story", "story_order", "story_start_context", "story_workflow"]
