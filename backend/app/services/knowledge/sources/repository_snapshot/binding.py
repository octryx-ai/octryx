"""The recorded binding session → Workspace → repository of one launcher session (C-MCP).

On session start, ``octryx-claude`` reports the git repository of the user's cwd:

- a credential-free remote;
- the HEAD commit;
- whether the working tree is dirty;
- whether HEAD is on a remote-tracking branch;
- the branch.

:func:`bind_session_repository` records it on the gateway shadow session
(``metadata.repository_binding``). That binding is the session's deterministic "this codebase". A
dirty working tree is recorded as such, never hidden.

The binding names the Workspace's ``git_repository`` source for that remote:

- the existing source whose ``remote`` is that repository, whatever its fetch mode or key;
- otherwise a new ``local_snapshot`` source (``repo-<hash>``), created only when the Workspace
  allows local snapshots (``policy.py``).

A ``remote_git`` source (K7) is never written by an upload, but code impact still reads it.

An optional display ``name`` and ``version`` label (``labels.py``) are stored on a ``local_snapshot``
source and name it in citations and source lists; an invalid one refuses the binding
(``repository_label_invalid``), it is never cleaned up.

Link mode:

- **host** links only for a known host, a clean tree and a pushed HEAD;
- the platform's source viewer otherwise, because the host would not serve exactly that content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .....models import Session
from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from .....time_utils import utc_now
from ...code.codebase import HEAD_PUSHED
from ..sync.git_config import FETCH_LOCAL_SNAPSHOT, HEAD_COMMIT, HEAD_DIRTY
from ..sync.git_hosts import RepositoryLocation
from .labels import RepositoryLabelError, display_label, validate_labels, with_labels
from .policy import REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED, local_snapshots_allowed
from .remote import RemoteRefusedError, parse_remote, snapshot_connector_key

BINDING_METADATA_KEY = "repository_binding"
LINKS_HOST = "host"
LINKS_PLATFORM = "platform"
SNAPSHOT_ALLOWED = "allowed"
SNAPSHOT_DENIED = "denied"
REASON_HEAD_COMMIT_INVALID = "head_commit_invalid"
REASON_REPOSITORY_SOURCE_IS_REMOTE = "repository_source_is_remote"
_MAX_BRANCH_CHARS = 120
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class SnapshotRefusal:
    """An explicit refusal of the binding or the upload: ``denied`` or ``needs_configuration``."""

    state: str
    reason: str


def valid_commit(value: object) -> str | None:
    return value if type(value) is str and len(value) == 40 and set(value) <= _HEX else None


def link_mode(location: RepositoryLocation, *, dirty: bool, pushed: bool) -> str:
    return LINKS_HOST if location.host is not None and not dirty and pushed else LINKS_PLATFORM


async def repository_connector(
    db: AsyncSession, project_id: str, connector_key: str
) -> KnowledgeSourceConnector | None:
    return (
        await db.execute(
            select(KnowledgeSourceConnector).where(
                KnowledgeSourceConnector.project_id == project_id,
                KnowledgeSourceConnector.connector_key == connector_key,
                KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
            )
        )
    ).scalar_one_or_none()


async def _connector_for_remote(
    db: AsyncSession, project_id: str, location: RepositoryLocation
) -> KnowledgeSourceConnector | None:
    rows = (
        await db.execute(
            select(KnowledgeSourceConnector)
            .where(
                KnowledgeSourceConnector.project_id == project_id,
                KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
            )
            .order_by(KnowledgeSourceConnector.connector_key)
        )
    ).scalars()
    return next((row for row in rows if dict(row.scope or {}).get("remote") == location.url), None)


def _new_connector(project_id: str, location: RepositoryLocation, created_by: str) -> KnowledgeSourceConnector:
    return KnowledgeSourceConnector(
        project_id=project_id,
        connector_key=snapshot_connector_key(location),
        kind=CONNECTOR_KIND_GIT_REPOSITORY,
        # head_commit / head_dirty / head_pushed are run state: the commit the index is complete at.
        scope={
            "fetch_mode": FETCH_LOCAL_SNAPSHOT,
            "remote": location.url,
            "web_base": location.url if location.host is not None else None,
            HEAD_COMMIT: None,
            HEAD_DIRTY: False,
            HEAD_PUSHED: False,
        },
        products=[],
        version=None,
        max_items_per_run=0,
        cursor={},
        created_by=created_by,
    )


def fetch_mode_of(connector: KnowledgeSourceConnector) -> str:
    scope = connector.scope if isinstance(connector.scope, dict) else {}
    return str(scope.get("fetch_mode") or "")


async def bind_session_repository(
    db: AsyncSession, *, session: Session, user_id: str, workspace_id: str, payload: dict[str, Any]
) -> dict[str, Any] | SnapshotRefusal:
    """Record the launcher's repository on ``session``; the answer the launcher prints. Flushes only."""
    reported = _reported(payload)
    if isinstance(reported, SnapshotRefusal):
        return reported
    location, head_commit, name, version = reported
    dirty = payload.get("head_dirty") is True
    pushed = payload.get("head_pushed") is True
    branch = payload.get("branch")
    branch = branch[:_MAX_BRANCH_CHARS] if type(branch) is str and branch.isprintable() else None
    root = payload.get("root")
    # The checkout's absolute local path: the only place a confirmed change workflow may edit.
    valid_root = type(root) is str and root.startswith("/") and len(root) <= 1024 and root.isprintable()
    root = root.rstrip("/") if valid_root else None

    connector, snapshot_reason = await _snapshot_source(db, workspace_id, location, user_id, name, version)
    connector_key = connector.connector_key if connector is not None else snapshot_connector_key(location)
    links = link_mode(location, dirty=dirty, pushed=pushed)
    binding = {
        "connector_key": connector_key,
        "connector_id": connector.id if connector is not None else None,
        "repository": location.path,
        "remote": location.url,
        "head_commit": head_commit,
        "head_dirty": dirty,
        "head_pushed": pushed,
        "branch": branch,
        "root": root,
        "links": links,
        "bound_at": utc_now().isoformat(),
    }
    metadata = dict(session.metadata_ or {})
    metadata[BINDING_METADATA_KEY] = binding
    session.metadata_ = metadata
    flag_modified(session, "metadata_")
    await db.flush()
    return {
        "state": "bound",
        "binding": {
            "connector_key": connector_key,
            "repository": location.path,
            "workspace_id": workspace_id,
            "head_commit": head_commit,
            "head_dirty": dirty,
            "links": links,
            "label": display_label(dict(connector.scope or {})) if connector is not None else None,
        },
        "snapshot": {
            "state": SNAPSHOT_DENIED if snapshot_reason else SNAPSHOT_ALLOWED,
            "reason": snapshot_reason,
        },
    }


def _reported(payload: dict[str, Any]):
    """The reported remote, HEAD commit and labels, or the refusal of the first invalid one."""
    try:
        location = parse_remote(payload.get("remote_url"))
    except RemoteRefusedError as error:
        return SnapshotRefusal("needs_configuration" if error.reason.endswith("missing") else "denied", error.reason)
    head_commit = valid_commit(payload.get("head_commit"))
    if head_commit is None:
        return SnapshotRefusal("denied", REASON_HEAD_COMMIT_INVALID)
    try:
        name, version = validate_labels(payload.get("name"), payload.get("version"))
    except RepositoryLabelError as error:
        return SnapshotRefusal("denied", error.reason)
    return location, head_commit, name, version


async def _snapshot_source(
    db: AsyncSession, workspace_id: str, location: RepositoryLocation, user_id: str, name, version
) -> tuple[KnowledgeSourceConnector | None, str | None]:
    """The Workspace's source for the remote (created when snapshots are allowed), and why it takes no upload."""
    allowed = await local_snapshots_allowed(db, workspace_id)
    connector = await _connector_for_remote(db, workspace_id, location)
    if connector is None and allowed:
        connector = _new_connector(workspace_id, location, user_id)
        db.add(connector)
        await db.flush()
    snapshot_reason = None
    if not allowed:
        snapshot_reason = REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED
    elif connector is not None and fetch_mode_of(connector) != FETCH_LOCAL_SNAPSHOT:
        snapshot_reason = REASON_REPOSITORY_SOURCE_IS_REMOTE
    if connector is not None and snapshot_reason is None and (name or version):
        connector.scope = with_labels(dict(connector.scope or {}), name, version)
        flag_modified(connector, "scope")
    return connector, snapshot_reason


def session_binding(session: Session) -> dict[str, Any] | None:
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    binding = metadata.get(BINDING_METADATA_KEY)
    return dict(binding) if isinstance(binding, dict) else None


__all__ = [
    "BINDING_METADATA_KEY",
    "LINKS_HOST",
    "LINKS_PLATFORM",
    "SnapshotRefusal",
    "bind_session_repository",
    "fetch_mode_of",
    "link_mode",
    "repository_connector",
    "session_binding",
    "valid_commit",
]
