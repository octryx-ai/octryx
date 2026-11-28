"""One page of unattended epic documentation: create under the granted parent or update the grant's own page."""

from __future__ import annotations

from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkItemDocument
from ....models.runtime.secure_work import WorkItem
from ....tools._confluence_instance import EXPECTED_CONNECTION_PARAM, EXPECTED_INSTANCE_PARAM
from ..platform.dispatch import SUCCEEDED, ToolOutcome, dispatch_tool
from ..records import record_event
from .auto_grant import _keep, _StopError

MARKER = "octryx-doc-grant"
EVENT_WRITTEN = "documentation_page_written"
PROVIDER = "confluence"


def _pinned(target: dict[str, Any]) -> dict[str, str]:
    return {"space_key": str(target["space_key"]), EXPECTED_INSTANCE_PARAM: str(target["instance"]),
            EXPECTED_CONNECTION_PARAM: str(target["connection_id"])}


def _mark(grant: dict[str, Any], slot: str) -> str:
    return f"{MARKER}:{grant['id']}:{slot}"


def _at_target(result: dict[str, Any], target: dict[str, Any]) -> bool:
    return (str(result.get("instance") or "") == target["instance"]
            and str(result.get("space_key") or "").upper() == target["space_key"]
            and str(result.get("parent_id") or "") == target["parent_page_id"])


async def _parent_ok(db: AsyncSession, run: WorkflowRun, target: dict[str, Any]) -> None:
    read = await dispatch_tool(db, run, "get_confluence_page", {
        **_pinned(target), "page_id": target["parent_page_id"]}, capability_class="read_only")
    if not read.ok:
        raise _StopError("parent_unreadable", {"reason": read.reason[:300]}, failed=True)
    if (str(read.result.get("instance") or "") != target["instance"]
            or str(read.result.get("space_key") or "").upper() != target["space_key"]):
        raise _StopError("parent_elsewhere", {"parent_page_id": target["parent_page_id"]})


async def _put(db: AsyncSession, run: WorkflowRun, grant: dict[str, Any], slot: str, title: str,
               body: str) -> ToolOutcome:
    target, mark = dict(grant["target"]), _mark(grant, slot)
    content = f"<p><em>Published by Octryx workflow run {escape(run.id)} ({escape(mark)}).</em></p>{body}"
    known = dict(dict(grant.get("pages") or {}).get(slot) or {})
    page_id = str(known.get("page_id") or "")
    if page_id:
        read = await dispatch_tool(db, run, "get_confluence_page", {**_pinned(target), "page_id": page_id},
                                   capability_class="read_only")
        if not read.ok:
            return read
    else:
        read = await dispatch_tool(db, run, "get_confluence_page", {**_pinned(target), "title": title},
                                   capability_class="read_only")
        if not read.ok and not (read.result.get("not_found") is True and read.result.get("lookup") == "title"
                                and read.result.get("instance") == target["instance"]):
            return read  # no proof the title is free: nothing is created
        page_id = str(read.result.get("id") or "") if read.ok else ""
    if page_id and (mark not in str(read.result.get("content") or "") or not _at_target(read.result, target)):
        # Never another person's page, never a page of ours that left the granted place.
        raise _StopError("foreign_page" if mark not in str(read.result.get("content") or "") else "page_moved",
                    {"slot": slot, "page_id": page_id, "title": title})
    if page_id:
        written = await dispatch_tool(db, run, "update_confluence_page", {
            **_pinned(target), "page_id": page_id, "content": content, "new_title": title,
            "expected_version": int(read.result.get("version") or 1)}, capability_class="deliver")
        operation = "updated"
    else:
        written = await dispatch_tool(db, run, "create_confluence_page", {
            **_pinned(target), "title": title, "content": content, "parent_id": target["parent_page_id"]},
            capability_class="deliver")
        operation = "created"
    if not written.ok:
        return written
    page = {"page_id": str(written.result.get("id") or page_id), "title": title,
            "url": str(written.result.get("url") or known.get("url") or read.result.get("url") or ""),
            "version": written.result.get("version")}
    grant["pages"] = {**dict(grant.get("pages") or {}), slot: page}
    _keep(run, grant)
    record_event(db, run, EVENT_WRITTEN, node_id=run.current_node_id, detail={
        "slot": slot, "operation": operation, "grant_id": grant["id"], "space_key": target["space_key"], **page})
    if slot != "spec":  # the spec file itself is ingested with its repository link (``publish_spec``)
        from .knowledge_documents import ingest_run_document, source_key, storage_to_markdown

        # what the platform writes becomes Workspace knowledge immediately (knowledge-first).
        await ingest_run_document(db, run, key=source_key("confluence", target["space_key"], page["page_id"]),
                                  title=title, text=storage_to_markdown(content), source_url=page["url"] or None,
                                  detail={"slot": slot, "page_version": page.get("version")})
    return ToolOutcome(SUCCEEDED, {**page, "operation": operation})


async def _bind_item(db: AsyncSession, run: WorkflowRun, item: WorkItem | None, grant: dict[str, Any],
                     page: dict[str, Any]) -> None:
    if item is None:
        return
    target = grant["target"]
    row = (await db.execute(select(WorkItemDocument).where(
        WorkItemDocument.work_item_id == item.id, WorkItemDocument.provider == PROVIDER,
        WorkItemDocument.connection_id == target["connection_id"],
        WorkItemDocument.instance_url == target["instance"],
        WorkItemDocument.page_id == page["page_id"]))).scalar_one_or_none()
    if row is None:
        row = WorkItemDocument(work_item_id=item.id, project_id=run.project_id, provider=PROVIDER,
                               connection_id=target["connection_id"], instance_url=target["instance"],
                               space_key=target["space_key"], page_id=page["page_id"], title=page["title"])
        db.add(row)
    row.title, row.url, row.version, row.run_id = page["title"], page["url"], page["version"], run.id
    await db.flush()
