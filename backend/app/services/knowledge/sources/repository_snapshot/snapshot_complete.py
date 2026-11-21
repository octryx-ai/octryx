"""Completing an open snapshot pass: retire removed paths, move the source's head, audit (``upload.py``)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.services.knowledge.code import repository_reads

from .....models import AuditLog, Session
from .....models.project.knowledge_source_sync import KnowledgeSourceConnector
from .....time_utils import utc_now
from ...code import repository_index
from ...code.codebase import HEAD_PUSHED
from ..sync.cursor import SyncCursor
from ..sync.git_config import HEAD_COMMIT, HEAD_DIRTY
from ..sync.git_repository import external_id_of
from ..sync.items import ConnectorRef, load_item, retire_item
from .binding import SnapshotRefusal
from .snapshot_pass import REASON_NO_OPEN_PASS, _open_snapshot, _Pass, _store_cursor, _writable_pass

# The upload module's logger, so the completion's log line keeps its origin.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".upload")

SNAPSHOT_AUDIT_ACTION = "knowledge.repository_snapshot.indexed"


async def complete_snapshot_pass(
    db: AsyncSession, *, session: Session, workspace_id: str, user_id: str, payload: dict[str, Any]
) -> dict[str, Any] | SnapshotRefusal:
    """Close the pass when nothing is wanted any more: retire removed paths, move the source's head."""
    opened = await _writable_pass(
        db, session=session, workspace_id=workspace_id, head_commit=payload.get("head_commit")
    )
    if isinstance(opened, SnapshotRefusal):
        return opened
    connector = opened.connector
    snapshot = _open_snapshot(connector, opened.head_commit)
    if snapshot is None:
        return SnapshotRefusal("needs_configuration", REASON_NO_OPEN_PASS)
    missing = len(snapshot.get("wanted") or {})
    if missing:
        return {"state": "incomplete", "files_indexed": 0, "files_new": 0, "files_removed": 0, "missing": missing}
    removed = await _retire_removed(db, connector, opened.head_commit)
    index = await repository_reads.load_repository_index(
        db, connector_id=connector.id, head_commit=opened.head_commit
    )
    scope = _move_head(connector, opened)
    counts = {
        "files_indexed": index.file_count,
        "files_new": int(snapshot.get("ingested") or 0),
        "files_removed": len(removed),
        "listed": int(snapshot.get("listed") or 0),
        "truncated": snapshot.get("truncated") is True,
    }
    db.add(_completion_audit(connector, opened, scope, session, workspace_id, user_id, counts))
    await db.flush()
    logger.info(
        "Repository snapshot indexed: workspace=%s connector=%s files=%d new=%d removed=%d",
        workspace_id,
        connector.connector_key,
        counts["files_indexed"],
        counts["files_new"],
        counts["files_removed"],
    )
    return {
        "state": "indexed",
        "files_indexed": counts["files_indexed"],
        "files_new": counts["files_new"],
        "files_removed": counts["files_removed"],
        "missing": 0,
    }


async def _retire_removed(db: AsyncSession, connector: KnowledgeSourceConnector, head_commit: str) -> list:
    """Paths HEAD no longer lists: index rows deleted, sources tombstoned."""
    ref = ConnectorRef.of(connector)
    removed = await repository_index.retire_unseen(db, connector_id=connector.id, head_commit=head_commit)
    for path, _source_id in removed:
        item = await load_item(db, ref, external_id_of(path))
        if item is not None:
            await retire_item(db, item, withheld=False, outcome="removed_at_source")
    return removed


def _move_head(connector: KnowledgeSourceConnector, opened: _Pass) -> dict:
    """The source's head becomes the pass's HEAD and the pass completes; the new scope."""
    scope = dict(connector.scope or {})
    scope.update({
        HEAD_COMMIT: opened.head_commit,
        HEAD_DIRTY: opened.binding.get("head_dirty") is True,
        HEAD_PUSHED: opened.binding.get("head_pushed") is True,
    })
    connector.scope = scope
    flag_modified(connector, "scope")
    _store_cursor(connector, SyncCursor.load(connector.cursor).complete_pass(utc_now()), None)
    return scope


def _completion_audit(
    connector: KnowledgeSourceConnector, opened: _Pass, scope: dict, session: Session, workspace_id: str,
    user_id: str, counts: dict,
) -> AuditLog:
    """Audited with counts only."""
    return AuditLog(
        user_id=user_id,
        action=SNAPSHOT_AUDIT_ACTION,
        resource_type="knowledge_source_connector",
        resource_id=connector.id,
        details={
            "workspace_id": workspace_id,
            "connector_key": connector.connector_key,
            "commit": opened.head_commit,
            "head_dirty": scope[HEAD_DIRTY],
            "session_id": session.id,
            **counts,
        },
    )
