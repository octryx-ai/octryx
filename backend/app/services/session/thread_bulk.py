"""Bulk archive, delete and restore of chat threads."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project, Session
from .lifecycle import archive_session_tree, restore_session_tree
from .tree_cleanup import cleanup_session_descendants, collect_session_descendants
from .turn_stop import stop_session_turn
from .turn_tasks import effective_session_status
from .workspace import delete_session_workspace

logger = logging.getLogger(__name__)

ThreadBulkAction = Literal["archive", "delete", "restore"]
SkipReason = Literal["running", "not_found", "failed"]
BULK_CHUNK_SIZE = 200


@dataclass(slots=True)
class ThreadBulkResult:
    affected_ids: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    running: int = 0
    sub_chats: int = 0
    by_project: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "affected_ids": self.affected_ids,
            "skipped": self.skipped,
            "counts": {
                "affected": len(self.affected_ids),
                "skipped": len(self.skipped),
                "running": self.running,
                "sub_chats": self.sub_chats,
            },
            "by_project": self.by_project,
        }


async def _count_sub_chats(db: AsyncSession, root_ids: list[str]) -> int:
    total = 0
    seen: set[str] = set(root_ids)
    pending = list(root_ids)
    while pending:
        children = (
            await db.execute(select(Session.id).where(Session.parent_session_id.in_(pending[:BULK_CHUNK_SIZE])))
        ).scalars().all()
        pending = pending[BULK_CHUNK_SIZE:]
        fresh = [child for child in children if child not in seen]
        seen.update(fresh)
        total += len(fresh)
        pending.extend(fresh)
    return total


async def _project_breakdown(db: AsyncSession, sessions: list[Session]) -> list[dict[str, Any]]:
    counts = Counter(str(session.project_id or "") for session in sessions)
    project_ids = [project_id for project_id in counts if project_id]
    names: dict[str, str] = {}
    if project_ids:
        rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all()
        names = {str(project_id): str(name or "") for project_id, name in rows}
    breakdown = [
        {"project_id": project_id, "project_name": names.get(project_id, "") if project_id else "No project",
         "count": count}
        for project_id, count in counts.items()
    ]
    return sorted(breakdown, key=lambda row: (row["project_id"] != "", row["project_name"].lower()))


async def _delete_thread(db: AsyncSession, session_id: str, *, running: bool) -> None:
    if running:
        session = await db.get(Session, session_id)
        if session is not None:
            await stop_session_turn(db, session)
    for descendant_id in await collect_session_descendants(db, session_id):
        await delete_session_workspace(db, descendant_id)
    await cleanup_session_descendants(db, session_id)


async def _apply_one(
    db: AsyncSession, *, action: ThreadBulkAction, session_id: str, running: bool, user_id: str
) -> None:
    if action == "archive":
        await archive_session_tree(db, session_id=session_id, user_id=user_id)
    elif action == "restore":
        await restore_session_tree(db, session_id=session_id, user_id=user_id)
    else:
        await _delete_thread(db, session_id, running=running)


async def apply_thread_bulk_action(
    db: AsyncSession,
    *,
    user_id: str,
    action: ThreadBulkAction,
    sessions: list[Session],
    not_found_ids: list[str],
    dry_run: bool = False,
) -> ThreadBulkResult:
    result = ThreadBulkResult(skipped=[{"id": item, "reason": "not_found"} for item in not_found_ids])
    # Plain values first: committing expires the ORM rows.
    targets: list[tuple[str, bool]] = []
    for session in sessions:
        running = effective_session_status(session) == "running"
        result.running += int(running)
        if running and action == "archive":
            result.skipped.append({"id": session.id, "reason": "running"})
        else:
            targets.append((session.id, running))
    if dry_run:
        result.affected_ids = [session_id for session_id, _running in targets]
        result.sub_chats = await _count_sub_chats(db, result.affected_ids)
        result.by_project = await _project_breakdown(db, sessions)
        return result

    for session_id, running in targets:
        try:
            await _apply_one(db, action=action, session_id=session_id, running=running, user_id=user_id)
            await db.commit()
        except Exception:  # noqa: BLE001 - one failing thread is reported, the rest still runs
            await db.rollback()
            logger.exception("Bulk %s failed for thread %s", action, session_id)
            result.skipped.append({"id": session_id, "reason": "failed"})
            continue
        result.affected_ids.append(session_id)

    db.add(
        AuditLog(
            user_id=user_id,
            action=f"chat.threads.bulk_{action}",
            resource_type="chat_thread",
            resource_id="bulk",
            details={
                "action": action,
                "affected_ids": result.affected_ids,
                "skipped": result.skipped,
                "counts": {"affected": len(result.affected_ids), "skipped": len(result.skipped)},
            },
        )
    )
    await db.commit()
    return result


__all__ = ["BULK_CHUNK_SIZE", "ThreadBulkAction", "ThreadBulkResult", "apply_thread_bulk_action"]
