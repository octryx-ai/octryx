"""The governed ``local_snapshot`` upload of a checkout's tracked files at HEAD (C-MCP).

One snapshot is one listing **pass** of the source (``sync/cursor.SyncCursor``), in three calls of
the launcher:

1. :func:`open_snapshot_pass` takes the manifest: path, blob sha1 and size of every tracked file at
   HEAD.
   - It refuses a pass for any commit but the session's bound HEAD.
   - It classifies every entry with the source model's closed outcomes (``classification.py``).
   - It answers the paths it still **wants**. A path whose blob is already indexed is unchanged;
     it only moves to the new commit, so re-ingest is incremental by sha.
   - While the pass is open, the codebase resolver answers ``repository_sync_in_progress``, so code
     impact never mixes two commits.
2. :func:`upload_snapshot_files` takes the wanted files' bytes, in bounded batches.
   - Every file must be wanted with exactly that blob, and its bytes must hash to it (git blob
     sha1) before anything is stored.
   - Each item is ingested by ``code_ingest.ingest_code_source``, the one ingestion of every fetch
     mode (code-aware spans, line ranges, line-preserving redaction).
   - It then records the file's sync item (version marker = blob sha1, content hash of the original
     bytes, as the ``remote_git`` runner does) and its code index row.
3. :func:`complete_snapshot_pass` completes only a pass with nothing left wanted.
   - Paths HEAD no longer lists are retired: their index rows are deleted and their sources
     tombstoned.
   - The source's ``head_commit``, ``head_dirty`` and ``head_pushed`` become the HEAD's.
   - The completion is audited with counts only.

Opening a pass enables Knowledge for the Workspace the way a connector run does
(``projection/workspace_knowledge_state.ensure_knowledge_enabled``: idempotent, audited), so the projection
never fails as ``not_configured``. A file is titled ``<repository>:<path>`` (``labels.py``), so its
citations name the repository. The per-file bound is ``Settings.knowledge_snapshot_max_file_bytes``
(default 1 MiB); a batch always admits one file of that size.

Scope: the Workspace is the gateway identity's, authorized for the user like a tool run. Uploading
needs the Workspace flag ``allow_local_snapshots`` and a ``local_snapshot`` source; a ``remote_git``
source is never written by an upload. Every function flushes and the route commits. Ingestion
commits on its own, as in the sync runner.
"""

from __future__ import annotations

from typing import Any

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
    db: AsyncSession, *, session: Session, workspace_id: str, user_id: str, payload: dict[str, Any]
) -> dict[str, Any] | SnapshotRefusal:
    """Start (or restart) the pass for the bound HEAD from its manifest; the wanted paths."""
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
    skipped: list[dict[str, str]] = []
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
    snapshot = {
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
