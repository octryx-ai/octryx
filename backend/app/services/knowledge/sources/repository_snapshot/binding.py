"""The recorded binding session, Workspace and repository of one launcher session. The binding is the session's
deterministic "this codebase"."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .....models import Session
from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from .....time_utils import utc_now
from ...code.codebase import HEAD_PUSHED
from ..sync.git_config import FETCH_LOCAL_SNAPSHOT, HEAD_COMMIT, HEAD_DIRTY
from ..sync.git_hosts import RepositoryLocation
from .labels import display_label
from .policy import REASON_LOCAL_SNAPSHOTS_NOT_ALLOWED, local_snapshots_allowed
from .protocol_types import BindRequest, BindResponse, LinkMode, SessionBinding
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
    state: str
    reason: str


def valid_commit(value: object) -> str | None:
    return value if type(value) is str and len(value) == 40 and set(value) <= _HEX else None


def link_mode(location: RepositoryLocation, *, dirty: bool, pushed: bool) -> LinkMode:
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
    db: AsyncSession, *, session: Session, user_id: str, workspace_id: str, payload: BindRequest
) -> BindResponse | SnapshotRefusal:
    reported = _reported(payload)
    if isinstance(reported, SnapshotRefusal):
        return reported
    location, head_commit = reported
    dirty = payload.get("head_dirty") is True
    pushed = payload.get("head_pushed") is True
    branch = payload.get("branch")
    branch = branch[:_MAX_BRANCH_CHARS] if type(branch) is str and branch.isprintable() else None
    root = payload.get("root")
    # The checkout's absolute local path: the only place a confirmed change workflow may edit.
    valid_root = type(root) is str and root.startswith("/") and len(root) <= 1024 and root.isprintable()
    root = root.rstrip("/") if valid_root else None

    connector, snapshot_reason = await _snapshot_source(db, workspace_id, location, user_id)
    connector_key = connector.connector_key if connector is not None else snapshot_connector_key(location)
    links = link_mode(location, dirty=dirty, pushed=pushed)
    binding: SessionBinding = {
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


def _reported(payload: BindRequest):
    try:
        location = parse_remote(payload.get("remote_url"))
    except RemoteRefusedError as error:
        return SnapshotRefusal("needs_configuration" if error.reason.endswith("missing") else "denied", error.reason)
    head_commit = valid_commit(payload.get("head_commit"))
    if head_commit is None:
        return SnapshotRefusal("denied", REASON_HEAD_COMMIT_INVALID)
    return location, head_commit


async def _snapshot_source(
    db: AsyncSession, workspace_id: str, location: RepositoryLocation, user_id: str
) -> tuple[KnowledgeSourceConnector | None, str | None]:
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
    return connector, snapshot_reason


def session_binding(session: Session) -> SessionBinding | None:
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
