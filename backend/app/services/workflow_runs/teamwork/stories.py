"""The coordinator splits an epic into stories; the server creates them."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..epic_chain import STORIES_KEY, STORY_WORKFLOW_KEY
from ..platform.dispatch import APPROVAL_PENDING, FAILED, SUCCEEDED, ToolOutcome, dispatch_tool

OUTPUT_KIND = "story_plan"
PROGRESS_KEY = "story_split"
DEFAULT_JIRA_ISSUE_TYPE = "Story"
PLATFORM_STORY_TYPE = "task"  # platform items know no "story" type


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> list[str]:
    return [text for entry in value if (text := _text(entry))] if isinstance(value, list) else []


def validate_story_plan(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    stories_raw = raw.get("stories") if isinstance(raw, dict) else None
    if not isinstance(stories_raw, list) or not stories_raw:
        return {"stories": []}, ["stories: at least one story, in build order"]
    stories: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(stories_raw, start=1):
        entry = entry if isinstance(entry, dict) else {}
        story = {"title": _text(entry.get("title")), "goal": _text(entry.get("goal")),
                 "criteria": _texts(entry.get("criteria")), "spec_sections": _texts(entry.get("spec_sections")),
                 "depends_on_titles": _texts(entry.get("depends_on_titles"))}
        name = story["title"] or f"#{index}"
        if not story["title"]:
            problems.append(f"story {index}: title is required")
        elif story["title"].casefold() in seen:
            problems.append(f"story {index}: title '{story['title']}' is used twice")
        if not story["criteria"]:
            problems.append(f"story '{name}': at least one acceptance criterion")
        for title in story["depends_on_titles"]:
            if title.casefold() not in seen:
                problems.append(f"story '{name}': depends on '{title}', which is no story before it")
        if story["title"]:
            seen.setdefault(story["title"].casefold(), index)
        stories.append(story)
    return {"stories": stories}, problems


def story_description(story: dict[str, Any]) -> str:
    parts = [story.get("goal") or ""]
    if story.get("criteria"):
        parts.append("Acceptance criteria:\n" + "\n".join(f"- {item}" for item in story["criteria"]))
    if story.get("spec_sections"):
        parts.append("Specification sections:\n" + "\n".join(f"- {item}" for item in story["spec_sections"]))
    if story.get("depends_on_titles"):
        parts.append("Builds on: " + ", ".join(story["depends_on_titles"]))
    return "\n\n".join(part for part in parts if part).strip()


async def _children(db: AsyncSession, epic: WorkItem) -> list[WorkItem]:
    return list((await db.execute(
        select(WorkItem).where(WorkItem.epic_key == epic.source_key, WorkItem.project_id == epic.project_id)
        .order_by(WorkItem.created_at, WorkItem.source_key))).scalars().all())


def _progress(run: WorkflowRun, created: dict[str, str]) -> None:
    run.context = {**dict(run.context or {}), PROGRESS_KEY: {"created": dict(created)}}


def _record(run: WorkflowRun, keys: list[str], params: dict[str, Any], created: dict[str, str]) -> None:
    _progress(run, created)
    context = dict(run.context or {})
    context[STORIES_KEY] = keys
    chosen = _text(params.get("story_workflow"))
    if chosen and not _text(context.get(STORY_WORKFLOW_KEY)):
        context[STORY_WORKFLOW_KEY] = chosen  # the definition's default; a run's own choice stays
    run.context = context


async def _jira_story(db: AsyncSession, run: WorkflowRun, epic: WorkItem, story: dict[str, Any],
                      issue_type: str) -> tuple[ToolOutcome, WorkItem | None]:
    description = story_description(story)
    outcome = await dispatch_tool(db, run, "create_jira_ticket", {
        "project_key": _text(epic.source_project_key) or epic.source_key.split("-")[0],
        "summary": story["title"], "description": description, "issue_type": issue_type,
        "parent_key": epic.source_key, "labels": ["workflow-run"],
    }, capability_class="deliver")
    key = _text(outcome.result.get("ticket_id")) if outcome.ok else ""
    if not key:
        return outcome, None
    item = WorkItem(project_id=epic.project_id, sync_config_id=epic.sync_config_id, source_type=epic.source_type,
                    source_instance=epic.source_instance, source_id=_text(outcome.result.get("id")) or None,
                    source_project_key=epic.source_project_key, source_key=key, title=story["title"][:500],
                    description=description or None, issue_type=issue_type, parent_key=epic.source_key,
                    epic_key=epic.source_key, work_state="intake")
    return outcome, await _insert_or_synced(db, item, epic)


async def _insert_or_synced(db: AsyncSession, item: WorkItem, epic: WorkItem) -> WorkItem:
    # The Jira sync can insert the same key between the ticket creation and this insert; a row of another Workspace
    # is never touched.
    from ...secure_work.workspace_immutable import insert_source_item

    synced = await insert_source_item(db, item)
    if synced is item:
        return item
    synced.epic_key = synced.epic_key or epic.source_key
    synced.parent_key = synced.parent_key or epic.source_key
    await db.flush()
    return synced


async def _platform_story(db: AsyncSession, run: WorkflowRun, epic: WorkItem, story: dict[str, Any]) -> WorkItem:
    from ...secure_work.platform_items import create_platform_work_item

    requester = await db.get(User, run.requested_by)
    return await create_platform_work_item(db, current_user=requester, project_id=epic.project_id,
                                           title=story["title"], description=story_description(story),
                                           issue_type=PLATFORM_STORY_TYPE, epic_key=epic.source_key)


async def create_stories(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from ...secure_work.platform_items import is_platform_work_item
    from ..phase_outputs import recorded_output

    epic = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if epic is None or _text(epic.issue_type).lower() != "epic":
        return ToolOutcome(FAILED, reason="the run's Work item is no epic: nothing to split into stories")
    if epic.project_id != run.project_id:
        return ToolOutcome(FAILED, reason="the epic belongs to another Workspace than the run")
    context = dict(run.context or {})
    created = {str(title): str(key) for title, key in dict(dict(context.get(PROGRESS_KEY) or {}).get(
        "created") or {}).items()}
    children = await _children(db, epic)
    if children and not created:
        keys = [str(child.source_key) for child in children]
        _record(run, keys, params, created)
        return ToolOutcome(SUCCEEDED, {"status": "adopted", "stories": keys})
    envelope = recorded_output(run, OUTPUT_KIND) or {}
    stories = list(dict(envelope.get("record") or {}).get("stories") or [])
    if not stories:
        return ToolOutcome(FAILED, reason="no story plan was submitted in this run")
    issue_type = _text(params.get("issue_type")) or DEFAULT_JIRA_ISSUE_TYPE
    for story in stories:
        if story["title"] in created:
            continue
        if is_platform_work_item(epic):
            item = await _platform_story(db, run, epic, story)
        else:
            outcome, item = await _jira_story(db, run, epic, story, issue_type)
            if item is None:
                # What was made so far stays recorded: the retry (or the granted approval) creates only the rest.
                _progress(run, created)
                if outcome.state == APPROVAL_PENDING or not outcome.ok:
                    return outcome
                return ToolOutcome(FAILED, outcome.result, f"Jira answered no key for '{story['title']}'")
        created[story["title"]] = str(item.source_key)
    keys = [created[story["title"]] for story in stories]
    _record(run, keys, params, created)
    return ToolOutcome(SUCCEEDED, {"status": "created", "stories": keys})


__all__ = ["OUTPUT_KIND", "PROGRESS_KEY", "create_stories", "story_description", "validate_story_plan"]
