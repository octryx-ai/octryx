"""The open ``local_snapshot`` pass of a session's bound HEAD (``upload.py`` module doc), shared by its three calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .....models import Session
from .....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ..sync.cursor import SyncCursor
from ..sync.git_config import FETCH_LOCAL_SNAPSHOT
from .binding import SnapshotRefusal, fetch_mode_of, repository_connector, session_binding, valid_commit
from .policy import REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED, local_snapshots_allowed

# The open pass's wanted files and counters, beside the generic cursor fields.
SNAPSHOT_CURSOR_KEY = "snapshot"

REASON_NOT_BOUND = "repository_not_bound"
REASON_HEAD_COMMIT_MISMATCH = "head_commit_mismatch"
REASON_NO_SOURCE = "repository_source_missing"
REASON_NOT_LOCAL_SNAPSHOT = "repository_source_is_remote"
REASON_NO_OPEN_PASS = "snapshot_pass_not_open"


@dataclass(frozen=True, slots=True)
class _Pass:
    binding: dict[str, Any]
    connector: KnowledgeSourceConnector
    head_commit: str


async def _writable_pass(
    db: AsyncSession, *, session: Session, workspace_id: str, head_commit: object
) -> _Pass | SnapshotRefusal:
    binding = session_binding(session)
    if binding is None:
        return SnapshotRefusal("needs_configuration", REASON_NOT_BOUND)
    commit = valid_commit(head_commit)
    if commit is None or commit != binding.get("head_commit"):
        return SnapshotRefusal("denied", REASON_HEAD_COMMIT_MISMATCH)
    if not await local_snapshots_allowed(db, workspace_id):
        return SnapshotRefusal("denied", REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED)
    connector = await repository_connector(db, workspace_id, str(binding.get("connector_key") or ""))
    if connector is None:
        return SnapshotRefusal("needs_configuration", REASON_NO_SOURCE)
    if fetch_mode_of(connector) != FETCH_LOCAL_SNAPSHOT:
        return SnapshotRefusal("denied", REASON_NOT_LOCAL_SNAPSHOT)
    return _Pass(binding=binding, connector=connector, head_commit=commit)


def _open_snapshot(connector: KnowledgeSourceConnector, head_commit: str) -> dict[str, Any] | None:
    raw = connector.cursor if isinstance(connector.cursor, dict) else {}
    snapshot = raw.get(SNAPSHOT_CURSOR_KEY)
    if not SyncCursor.load(raw).pass_open or not isinstance(snapshot, dict) or snapshot.get("commit") != head_commit:
        return None
    return dict(snapshot)


def _store_cursor(connector: KnowledgeSourceConnector, cursor: SyncCursor, snapshot: dict[str, Any] | None) -> None:
    stored = cursor.as_dict()
    if snapshot is not None:
        stored[SNAPSHOT_CURSOR_KEY] = snapshot
    connector.cursor = stored
    flag_modified(connector, "cursor")
