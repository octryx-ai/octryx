"""Platform-native work items: agent-creatable epics and tasks.

These items live ONLY on the platform (``source_type="platform"``) — they are
never synced to Jira or any external tracker. Jira stays the manually
curated human task list; platform items are the working memory of agent
work: an LLM plans something, creates an epic, assigns tasks to it, and
links the CLI sessions that worked on them. A later worker (any MCP client)
pulls the full handover context — task, plan, notes, and the linked
sessions' conversation digests — and continues where the previous one
stopped.

Platform items reuse the full WorkItem machinery (workflows, change plans,
verification contracts, coding pipeline); only the tracker sync never
touches them.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkItem
from ...time_utils import utc_now
from ..project import get_project_config, get_user_project_ids

logger = logging.getLogger(__name__)

PLATFORM_SOURCE_TYPE = "platform"
PLATFORM_SOURCE_INSTANCE = "platform"
PLATFORM_SYNC_STATE = "platform_native"
# "story": spec-writing splits an epic into stories, not tasks.
PLATFORM_ISSUE_TYPES = {"epic", "story", "task", "bug", "improvement", "spike"}
DEFAULT_PLATFORM_KEY_PREFIX = "OCX"
_MAX_NOTES = 100
_MAX_NOTE_CHARS = 2000


# A create retries with the next key when a parallel one took its key (unique index); 17+ at once is a normal load.
KEY_ATTEMPTS = 64


def is_platform_work_item(item: WorkItem) -> bool:
    return str(item.source_type or "") == PLATFORM_SOURCE_TYPE


async def _require_project_access(db: AsyncSession, user: User, project_id: str) -> str:
    normalized = str(project_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="project_id is required")
    project_ids = await get_user_project_ids(user.id, db)
    if normalized not in project_ids:
        raise HTTPException(status_code=403, detail="User is not allowed to access this project")
    return normalized


def _key_number(key: object, prefix: str) -> int:
    match = re.match(rf"^{re.escape(prefix)}-(\d+)$", str(key or ""))
    return int(match.group(1)) if match else 0


async def _next_platform_key(db: AsyncSession, *, prefix: str, above: int = 0) -> str:
    """The next key after the highest stored one and after ``above`` (a number another create just took)."""
    rows = (
        await db.execute(
            select(WorkItem.source_key).where(
                WorkItem.source_type == PLATFORM_SOURCE_TYPE,
                WorkItem.source_key.like(f"{prefix}-%"),
            )
        )
    ).scalars().all()
    highest = max([above, *(_key_number(key, prefix) for key in rows)])
    return f"{prefix}-{highest + 1}"


async def create_platform_work_item(
    db: AsyncSession,
    *,
    current_user: User,
    project_id: str,
    title: str,
    description: str = "",
    issue_type: str = "task",
    epic_key: str = "",
    labels: list[str] | None = None,
    priority: str = "normal",
) -> WorkItem:
    """Create a platform-only work item; never reaches an external tracker."""
    project = await _require_project_access(db, current_user, project_id)
    normalized_title = str(title or "").strip()
    if not normalized_title:
        raise HTTPException(status_code=422, detail="title is required")
    normalized_type = str(issue_type or "task").strip().lower()
    if normalized_type not in PLATFORM_ISSUE_TYPES:
        allowed = ", ".join(sorted(PLATFORM_ISSUE_TYPES))
        raise HTTPException(status_code=422, detail=f"issue_type must be one of: {allowed}")

    normalized_epic = str(epic_key or "").strip()
    if normalized_epic:
        await _require_platform_epic(db, normalized_epic, project)

    config = await get_project_config(project, db)
    prefix = str(config.get("platform_task_prefix") or DEFAULT_PLATFORM_KEY_PREFIX).strip().upper()
    now = utc_now()

    fields = _platform_item_fields(
        project=project,
        prefix=prefix,
        title=normalized_title,
        description=description,
        issue_type=normalized_type,
        priority=priority,
        reporter=current_user.username,
        labels=labels,
        epic_key=normalized_epic,
        now=now,
    )
    item = await _insert_with_free_key(db, prefix=prefix, fields=fields)
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.platform_item_created",
            resource_type="work_item",
            resource_id=item.id,
            details={
                "source_key": item.source_key,
                "issue_type": normalized_type,
                "epic_key": normalized_epic or None,
                "project_id": project,
            },
        )
    )
    await _ingest_item_into_graph(db, item=item)
    await db.flush()
    return item


async def _require_platform_epic(db: AsyncSession, epic_key: str, project: str) -> None:
    epic = (
        await db.execute(
            select(WorkItem).where(
                WorkItem.source_type == PLATFORM_SOURCE_TYPE,
                WorkItem.source_key == epic_key,
            )
        )
    ).scalar_one_or_none()
    if epic is None or str(epic.issue_type or "") != "epic":
        raise HTTPException(
            status_code=422,
            detail=f"epic_key does not reference a platform epic: {epic_key}",
        )
    if epic.project_id != project:
        raise HTTPException(status_code=422, detail="epic belongs to a different project")


def _platform_item_fields(
    *,
    project: str,
    prefix: str,
    title: str,
    description: str,
    issue_type: str,
    priority: str,
    reporter: str,
    labels: list[str] | None,
    epic_key: str,
    now: Any,
) -> dict[str, Any]:
    """The new item's columns except its key, which ``_insert_with_free_key`` picks."""
    return {
        "project_id": project,
        "source_type": PLATFORM_SOURCE_TYPE,
        "source_instance": PLATFORM_SOURCE_INSTANCE,
        "source_project_key": prefix,
        "title": title[:500],
        "description": str(description or "").strip() or None,
        "issue_type": issue_type,
        "source_status": "open",
        "priority": str(priority or "normal").strip().lower(),
        "reporter": reporter,
        "labels_json": [str(label).strip() for label in labels or [] if str(label or "").strip()][:20],
        "epic_key": epic_key or None,
        "work_state": "intake",
        "sync_state": PLATFORM_SYNC_STATE,
        "source_created_at": now,
        "imported_at": now,
    }


async def _insert_with_free_key(db: AsyncSession, *, prefix: str, fields: dict[str, Any]) -> WorkItem:
    taken = 0
    # Parallel creates read the same highest key; the unique index refuses all but one. The refused ones take the
    # next free key in a savepoint instead of failing the request with a 500.
    for _attempt in range(KEY_ATTEMPTS):
        source_key = await _next_platform_key(db, prefix=prefix, above=taken)
        row = WorkItem(**fields, source_key=source_key)
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            taken = max(taken, _key_number(source_key, prefix))
            continue
        return row
    raise HTTPException(status_code=409, detail="no free work item key, retry")


async def _ingest_item_into_graph(db: AsyncSession, *, item: WorkItem) -> None:
    """Best effort: the task becomes a graph node like every synced ticket."""
    try:
        from ..knowledge_graph import ingest_ticket_record

        await ingest_ticket_record(
            db,
            project_id=item.project_id,
            ticket={
                "key": item.source_key,
                "title": item.title,
                "status": item.source_status,
                "priority": item.priority,
                "assignee_name": item.assignee,
            },
        )
    except Exception:  # noqa: BLE001 - graph must not block task creation
        logger.exception("platform_item.graph_ingest_failed", extra={"work_item_id": item.id})


async def add_work_item_note(
    db: AsyncSession,
    *,
    item: WorkItem,
    note: str,
    current_user: User,
    limit: int = _MAX_NOTE_CHARS,
) -> dict[str, Any]:
    """Append a progress note — the small handover breadcrumbs between workers (``limit``: a product owner's answer
    from a workflow run keeps its whole text)."""
    text = str(note or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="note is required")
    fields = dict(item.source_fields_json or {})
    notes = [entry for entry in fields.get("platform_notes") or [] if isinstance(entry, dict)]
    notes.append(
        {
            "at": utc_now().isoformat(),
            "author": current_user.username,
            "note": text[:limit],
        }
    )
    fields["platform_notes"] = notes[-_MAX_NOTES:]
    item.source_fields_json = fields
    await db.flush()
    return {"work_item": item.source_key, "notes": len(fields["platform_notes"])}


__all__ = [
    "PLATFORM_SOURCE_TYPE",
    "add_work_item_note",
    "create_platform_work_item",
    "is_platform_work_item",
]
