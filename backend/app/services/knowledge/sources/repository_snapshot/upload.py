"""The governed ``local_snapshot`` upload of a checkout's tracked files at HEAD. A pass is only for the session's bound
HEAD commit."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.code import repository_reads

from .....models import Session
from .....time_utils import utc_now
from ...access.authorization import authorize_tool_workspace
from ...code import repository_index
from ...projection.workspace_knowledge_state import ensure_knowledge_enabled
from ..sync.cursor import SyncCursor
from .binding import SnapshotRefusal, valid_commit
from .classification import manifest_outcome
from .protocol_types import ManifestRequest, ManifestResponse, SkippedPath, SnapshotPassState
from .snapshot_pass import _store_cursor, _writable_pass

MAX_MANIFEST_FILES = 10_000
REASON_MANIFEST_INVALID = "manifest_invalid"
REASON_MANIFEST_TOO_LARGE = "manifest_too_large"


def _manifest_entries(files: object) -> list[tuple[str, str, int]] | None:
    if not isinstance(files, list):
        return None
    entries: list[tuple[str, str, int]] = []
    for entry in files:
        if not isinstance(entry, dict):
            return None
        path, blob, size = entry.get("path"), valid_commit(entry.get("blob_sha")), entry.get("size")
        if type(path) is not str or blob is None or type(size) is not int or size < 0:
            return None
        entries.append((path, blob, size))
    return entries


async def open_snapshot_pass(
    db: AsyncSession, *, session: Session, workspace_id: str, user_id: str, payload: ManifestRequest
) -> ManifestResponse | SnapshotRefusal:
    opened = await _writable_pass(
        db, session=session, workspace_id=workspace_id, head_commit=payload.get("head_commit")
    )
    if isinstance(opened, SnapshotRefusal):
        return opened
    # Before anything is projected, Knowledge is enabled (idempotent and audited; it commits).
    authorized = await authorize_tool_workspace(
        db, user_id=user_id, project_id=workspace_id, allowed_project_ids=[workspace_id]
    )
    knowledge = await ensure_knowledge_enabled(db, authorized=authorized, actor_id=user_id)
    opened = await _writable_pass(
        db, session=session, workspace_id=workspace_id, head_commit=payload.get("head_commit")
    )
    if isinstance(opened, SnapshotRefusal):
        return opened
    entries = _manifest_entries(payload.get("files"))
    if entries is None:
        return SnapshotRefusal("denied", REASON_MANIFEST_INVALID)
    if len(entries) > MAX_MANIFEST_FILES:
        return SnapshotRefusal("denied", REASON_MANIFEST_TOO_LARGE)
    skipped: list[SkippedPath] = []
    listed: dict[str, str] = {}
    for path, blob, size in entries:
        outcome = manifest_outcome(path, size)
        if outcome is not None:
            skipped.append({"path": path[:200], "reason": outcome})
        else:
            listed[path] = blob
    connector = opened.connector
    indexed = await repository_reads.indexed_blobs(db, connector_id=connector.id, paths=list(listed))
    unchanged = [path for path, blob in listed.items() if indexed.get(path) == blob]
    await repository_index.mark_seen(db, connector_id=connector.id, commit_sha=opened.head_commit, paths=unchanged)
    wanted = {path: blob for path, blob in listed.items() if indexed.get(path) != blob}
    raw = connector.cursor if isinstance(connector.cursor, dict) else {}
    cursor = SyncCursor.load(raw).begin_pass(utc_now())
    snapshot: SnapshotPassState = {
        "commit": opened.head_commit,
        "wanted": wanted,
        "ingested": 0,
        "listed": len(listed),
        "truncated": payload.get("truncated") is True,
    }
    _store_cursor(connector, cursor, snapshot)
    await db.flush()
    return {
        "state": "ok",
        "wanted": sorted(wanted),
        "unchanged": len(unchanged),
        "skipped": skipped,
        "knowledge": knowledge,
    }


__all__ = ["MAX_MANIFEST_FILES", "open_snapshot_pass"]
