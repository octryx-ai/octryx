"""Unattended epic documentation: the spec page and a feature page per story."""

from __future__ import annotations

from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..platform.catalog import DOCUMENTATION_ROUTES, PUBLISH_FEATURE, PUBLISH_SPEC, SKIPPED
from ..platform.dispatch import APPROVAL_PENDING, FAILED, SUCCEEDED, ToolOutcome
from ..records import record_event
from .auto_grant import _grant, _StopError
from .auto_page_write import _bind_item, _parent_ok, _put
from .auto_render import _item_link, _link, _page_link, _pr, markdown_storage
from .spec_source import pushed_spec

ROUTES = DOCUMENTATION_ROUTES
EVENT_SKIPPED = "documentation_skipped"
EVENT_FAILED = "documentation_failed"


def _skip(db: AsyncSession, run: WorkflowRun, reason: str, **detail: Any) -> tuple[ToolOutcome, str]:
    record_event(db, run, EVENT_SKIPPED, node_id=run.current_node_id, detail={"reason": reason, **detail})
    return ToolOutcome(SUCCEEDED, {"status": SKIPPED, "reason": reason, **detail}, reason), SKIPPED


async def _pages(db: AsyncSession, run: WorkflowRun, grant: dict[str, Any],
                 pages: list[tuple[str, str, Any, WorkItem | None]]) -> tuple[ToolOutcome, str]:
    written: list[str] = []
    failed: list[str] = []
    for slot, title, render, item in pages:
        try:
            outcome = await _put(db, run, grant, slot, title, render(grant))
        except _StopError as stop:
            record_event(db, run, EVENT_SKIPPED, node_id=run.current_node_id,
                         detail={"reason": stop.reason, "slot": slot, **stop.detail})
            continue
        if outcome.state == APPROVAL_PENDING:
            return outcome, FAILED  # the run waits for the Workspace's tool approval (``run_platform_action``)
        if not outcome.ok:
            record_event(db, run, EVENT_FAILED, node_id=run.current_node_id, detail={
                "slot": slot, "title": title, "reason": outcome.reason[:500],
                "failure_class": outcome.failure_class or "external"})
            failed.append(f"{slot}: {outcome.reason[:200]}")
            continue
        await _bind_item(db, run, item, grant, outcome.result)
        written.append(slot)
    if failed:
        return ToolOutcome(FAILED, {"written": written}, "; ".join(failed)[:500],
                           failure_class="external"), FAILED
    if written:
        return ToolOutcome(SUCCEEDED, {"written": written, "pages": dict(grant.get("pages") or {})}), SUCCEEDED
    return ToolOutcome(SUCCEEDED, {"status": SKIPPED, "written": []}, "no page written"), SKIPPED


async def _guarded(db: AsyncSession, run: WorkflowRun, build: Any) -> tuple[ToolOutcome, str]:
    try:
        grant, epic, story = await _grant(db, run)
        await _parent_ok(db, run, grant["target"])
        pages = await build(grant, epic, story)
    except _StopError as stop:
        if stop.failed:
            record_event(db, run, EVENT_FAILED, node_id=run.current_node_id,
                         detail={"reason": stop.reason, **stop.detail})
            return ToolOutcome(FAILED, stop.detail, stop.reason, failure_class="external"), FAILED
        return _skip(db, run, stop.reason, **stop.detail)
    return await _pages(db, run, grant, pages)



async def publish_spec(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> tuple[ToolOutcome, str]:
    del params

    async def build(grant: dict[str, Any], epic: WorkItem | None, _story: WorkItem | None) -> list:
        if epic is None:
            raise _StopError("no_epic")
        path, text = await pushed_spec(run)
        if not text.strip():
            raise _StopError("spec_unavailable", {"head_sha": dict(run.context or {}).get("head_sha")})
        from .knowledge_documents import ingest_run_document, source_key, spec_url

        head = str(dict(run.context or {}).get("head_sha") or "")
        await ingest_run_document(db, run, key=source_key("spec", str(run.repository or ""), path), title=(
            f"Specification {epic.source_key}: {epic.title}"), text=text, source_url=spec_url(run, path, head),
            detail={"path": path, "head_sha": head})
        keys = [str(key) for key in dict(run.context or {}).get("stories") or []]
        stories = list((await db.execute(select(WorkItem).where(
            WorkItem.project_id == run.project_id, WorkItem.source_key.in_(keys)))).scalars().all()) if keys else []
        by_key = {str(story.source_key): story for story in stories}
        return [_spec_page(run, epic, path, text, keys, by_key, pull_request=True)]

    return await _guarded(db, run, build)


def _spec_page(run: WorkflowRun, epic: WorkItem, path: str, text: str, keys: list[str], by_key: dict[str, WorkItem],
               *, pull_request: bool) -> tuple[str, str, Any, WorkItem]:
    pr_id, pr_url = _pr(run) if pull_request else ("", "")

    def render(_grant: dict[str, Any]) -> str:
        listed = "".join(f"<li>{_item_link(by_key.get(key)) or escape(key)}</li>" for key in keys)
        return "".join([
            "<h2>Links</h2><ul>", f"<li>Epic: {_item_link(epic)}</li>",
            f"<li>Pull request: {_link('#' + pr_id if pr_id else 'open', pr_url)}</li>" if pr_url else "",
            f"<li>Source: <code>{escape(path)}</code> on <code>{escape(run.branch or '')}</code></li>", "</ul>",
            f"<h2>Stories in build order</h2><ol>{listed}</ol>" if listed else "",
            "<h2>Specification</h2>", markdown_storage(text)])

    return ("spec", f"{epic.source_key}: {epic.title} - Specification"[:255], render, epic)



async def _missing_spec(run: WorkflowRun, grant: dict[str, Any], epic: WorkItem,
                        listed: list[tuple[WorkItem, WorkflowRun | None]]) -> list:
    if dict(grant.get("pages") or {}).get("spec"):
        return []
    path, text = await pushed_spec(run)
    if not text.strip():
        return []
    keys = [str(item.source_key) for item, _found in listed]
    return [_spec_page(run, epic, path, text, keys, {str(item.source_key): item for item, _found in listed},
                       pull_request=False)]


async def _story_prs(db: AsyncSession, run: WorkflowRun, epic: WorkItem) -> list[tuple[WorkItem, WorkflowRun | None]]:
    from ..epic_chain import _stories, story_order

    stories = await _stories(db, run.project_id, str(epic.source_key), story_order(run))
    runs = list((await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id.in_([story.id for story in stories] or [""]),
        WorkflowRun.parent_run_id.is_(None)).order_by(WorkflowRun.created_at.desc()))).scalars().all())
    newest: dict[str, WorkflowRun] = {}
    for item in [run, *runs]:
        if item.work_item_id and item.work_item_id not in newest and _pr(item)[1]:
            newest[item.work_item_id] = item
    return [(story, newest.get(story.id)) for story in stories]


async def publish_feature(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> tuple[ToolOutcome, str]:
    del params

    async def build(grant: dict[str, Any], epic: WorkItem | None, story: WorkItem | None) -> list:
        if story is None or epic is None:
            raise _StopError("no_epic_story")
        pr_id, pr_url = _pr(run)
        listed = await _story_prs(db, run, epic)
        complete = bool(listed) and all(found is not None for _item, found in listed)
        overview_title = f"{epic.source_key}: {epic.title} - Overview"[:255]

        def feature(current: dict[str, Any]) -> str:
            return "".join([
                "<h2>Links</h2><ul>", f"<li>Story: {_item_link(story)}</li>",
                f"<li>Pull request: {_link('#' + pr_id if pr_id else 'open', pr_url)}</li>" if pr_url
                else "<li>Pull request: not opened</li>",
                f"<li>Branch: <code>{escape(run.branch or '')}</code></li>" if run.branch else "",
                _page_link(current, "spec", "Specification"), _page_link(current, "overview", "Epic overview"),
                "</ul>", "<h2>Story</h2>",
                "".join(f"<p>{escape(part)}</p>" for part in str(story.description or "").split("\n\n")
                        if part.strip())])

        def overview(current: dict[str, Any]) -> str:
            rows = []
            for item, found in listed:
                number, url = _pr(found) if found is not None else ("", "")
                page = dict(dict(current.get("pages") or {}).get(f"feature:{item.source_key}") or {})
                rows.append(f"<tr><td>{_item_link(item)}</td>"
                            f"<td>{_link('#' + number if number else 'open', url) if url else 'not yet'}</td>"
                            f"<td>{_link('page', str(page.get('url') or '')) if page else ''}</td></tr>")
            state = (f"All {len(listed)} stories of the epic have a pull request." if complete else
                     f"{sum(1 for _item, found in listed if found is not None)} of {len(listed)} stories have a "
                     "pull request so far.")
            return "".join([
                "<h2>Links</h2><ul>", f"<li>Epic: {_item_link(epic)}</li>",
                _page_link(current, "spec", "Specification"), "</ul>", f"<p>{escape(state)}</p>",
                "<h2>Stories in build order</h2><table><tbody><tr><th>Story</th><th>Pull request</th>"
                f"<th>Feature page</th></tr>{''.join(rows)}</tbody></table>"])

        pages = [(f"feature:{story.source_key}", f"{story.source_key}: {story.title}"[:255], feature, story),
                 ("overview", overview_title, overview, epic)]
        return [*(await _missing_spec(run, grant, epic, listed)), *pages]

    return await _guarded(db, run, build)


HANDLERS = {PUBLISH_SPEC: publish_spec, PUBLISH_FEATURE: publish_feature}

__all__ = [
    "EVENT_FAILED",
    "EVENT_SKIPPED",
    "HANDLERS",
    "ROUTES",
    "publish_feature",
    "publish_spec",
]
