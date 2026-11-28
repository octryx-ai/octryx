"""Which codebase a code question is about: one resolver, explicit precedence. The order is fixed and nothing is
guessed."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.sync.cursor import SyncCursor
from ..sources.sync.git_config import (
    FETCH_REMOTE_GIT,
    HEAD_COMMIT,
    HEAD_DIRTY,
    HOST_BASE,
    HOST_KIND,
    repository_location,
)
from .commit import checkout_commit

CODEBASE_SESSION_CHECKOUT = "session_checkout"
CODEBASE_WORKSPACE_REPOSITORY = "workspace_repository"
STATE_RESOLVED = "resolved"
STATE_INVALID_REQUEST = "invalid_request"
STATE_NEEDS_CLARIFICATION = "needs_clarification"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
REASON_NO_REPOSITORY_SOURCE = "no_repository_source"
REASON_UNKNOWN_REPOSITORY = "unknown_repository"
REASON_NOT_SYNCED = "repository_not_synced"
REASON_SYNC_IN_PROGRESS = "repository_sync_in_progress"
MAX_CANDIDATES = 20
HEAD_PUSHED = "head_pushed"


@dataclass(frozen=True, slots=True)
class RepositorySource:
    connector_id: str
    connector_key: str
    repository_url: str
    fetch_mode: str
    head_commit: str | None
    head_dirty: bool
    head_pushed: bool
    pass_open: bool
    # A Bitbucket Data Center repository's instance URL (``git_config.HOST_BASE``); ``None`` on a known host.
    datacenter_base: str | None = None

    def as_candidate(self) -> dict[str, object]:
        return {"repository": self.connector_key, "repository_url": self.repository_url, "commit": self.head_commit}

    def blob_link(self, path: str, line: int) -> str | None:
        if self.head_commit is None:
            return None
        if self.fetch_mode != FETCH_REMOTE_GIT and (self.head_dirty or not self.head_pushed):
            return None
        try:
            location = repository_location(self.repository_url, datacenter_base=self.datacenter_base)
        except InvalidEvidenceRequestError:
            return None
        return f"{location.blob_url(self.head_commit, path)}#L{line}"


@dataclass(frozen=True, slots=True)
class Codebase:
    kind: str
    commit: str | None
    root: Path | None = None
    repository: RepositorySource | None = None


@dataclass(frozen=True, slots=True)
class CodebaseRefusal:
    state: str
    reason: str
    candidates: tuple[dict[str, object], ...] = field(default=())


async def workspace_repositories(db: AsyncSession, project_id: str) -> tuple[RepositorySource, ...]:
    rows = (
        await db.execute(
            select(KnowledgeSourceConnector)
            .where(
                KnowledgeSourceConnector.project_id == project_id,
                KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
            )
            .order_by(KnowledgeSourceConnector.connector_key)
            .limit(MAX_CANDIDATES + 1)
        )
    ).scalars()
    sources = []
    for row in rows:
        scope = dict(row.scope or {})
        commit = scope.get(HEAD_COMMIT)
        sources.append(
            RepositorySource(
                connector_id=row.id,
                connector_key=row.connector_key,
                repository_url=str(scope.get("remote") or ""),
                fetch_mode=str(scope.get("fetch_mode") or ""),
                head_commit=commit if isinstance(commit, str) else None,
                head_dirty=scope.get(HEAD_DIRTY) is True,
                head_pushed=scope.get(HEAD_PUSHED) is True,
                pass_open=SyncCursor.load(row.cursor).pass_open,
                datacenter_base=str(scope.get(HOST_BASE) or "") if scope.get(HOST_KIND) else None,
            )
        )
    return tuple(sources)


def _readable(source: RepositorySource) -> Codebase | CodebaseRefusal:
    if source.head_commit is None:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_NOT_SYNCED, (source.as_candidate(),))
    if source.pass_open:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_SYNC_IN_PROGRESS, (source.as_candidate(),))
    return Codebase(CODEBASE_WORKSPACE_REPOSITORY, source.head_commit, repository=source)


def _by_key(sources: tuple[RepositorySource, ...], key: str, *, by_id: bool = False) -> Codebase | CodebaseRefusal:
    match = next(
        (source for source in sources if (source.connector_id if by_id else source.connector_key) == key), None
    )
    if match is None:
        candidates = tuple(source.as_candidate() for source in sources[:MAX_CANDIDATES])
        return CodebaseRefusal(STATE_INVALID_REQUEST, REASON_UNKNOWN_REPOSITORY, candidates)
    return _readable(match)


async def resolve_codebase(
    db: AsyncSession,
    *,
    project_id: str,
    explicit_root: Path | None = None,
    repository: str | None = None,
    session_root: Path | None = None,
    session_target: object | None = None,
) -> Codebase | CodebaseRefusal:
    if explicit_root is not None and repository is not None:
        return CodebaseRefusal(STATE_INVALID_REQUEST, "path_and_repository")
    if explicit_root is not None:
        return Codebase(CODEBASE_SESSION_CHECKOUT, checkout_commit(explicit_root), root=explicit_root)
    sources = await workspace_repositories(db, project_id)
    if repository is not None:
        return _by_key(sources, repository)
    if session_root is not None and session_root.is_dir() and (commit := checkout_commit(session_root)):
        return Codebase(CODEBASE_SESSION_CHECKOUT, commit, root=session_root)
    if isinstance(session_target, CodebaseRefusal):
        return session_target
    if session_target is not None:
        return _by_key(sources, str(getattr(session_target, "connector_id", "")), by_id=True)
    if len(sources) == 1:
        return _readable(sources[0])
    if not sources:
        return CodebaseRefusal(STATE_NEEDS_CONFIGURATION, REASON_NO_REPOSITORY_SOURCE)
    return CodebaseRefusal(
        STATE_NEEDS_CLARIFICATION,
        "several_repository_sources",
        tuple(source.as_candidate() for source in sources[:MAX_CANDIDATES]),
    )


__all__ = [
    "CODEBASE_SESSION_CHECKOUT",
    "CODEBASE_WORKSPACE_REPOSITORY",
    "Codebase",
    "CodebaseRefusal",
    "RepositorySource",
    "resolve_codebase",
    "workspace_repositories",
]
