"""What a ``git_repository`` run adds to the generic Source Sync run."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    RUN_STATE_COMPLETED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from ...code.repository_index import mark_seen, retire_unseen
from ..repository_snapshot.labels import repository_label
from .contract import REASON_SNAPSHOT_UPLOAD_REQUIRED
from .git_clone import GitCloneReader
from .git_config import FETCH_REMOTE_GIT, HEAD_COMMIT, HEAD_DIRTY, GitScope
from .git_repository import GitRepositoryConnector
from .runner import SyncRefusedError
from .stored_types import RepositoryRunFacts

_NO_COMMIT = "0" * 40  # Git's null object id: no indexed file was ever seen at it


def git_connector(
    row: KnowledgeSourceConnector, *, transport=None, connection=None, clone_reader=None
) -> GitRepositoryConnector:
    scope = dict(row.scope or {})
    if scope.get("fetch_mode") != FETCH_REMOTE_GIT:
        raise SyncRefusedError(REASON_SNAPSHOT_UPLOAD_REQUIRED)
    # A host read through a connection (Bitbucket Cloud, Data Center) gets exactly the connection resolved for it.
    auth = getattr(connection, "auth", None)
    bearer = getattr(connection, "bearer", None)  # a GitHub connection's token (git_bitbucket.linked_git_connection)
    credential = getattr(connection, "credential", None)
    # A repository with its own Git token clones with it (``repository_git_token.py``); REST keeps the connection.
    git_token = getattr(connection, "git_token", None)
    clone = clone_reader or (
        GitCloneReader(credential=credential, git_token=git_token, oidc_transport=transport) if credential else None
    )
    return GitRepositoryConnector(
        GitScope.load(scope), transport=transport, label=repository_label(scope), auth=auth, clone=clone,
        bearer=bearer,
    )


async def record_git_run(
    db: AsyncSession, *, connector_id: str, run: KnowledgeSourceSyncRun, connector: GitRepositoryConnector
) -> None:
    row = await db.get(KnowledgeSourceConnector, connector_id)
    scope = dict(row.scope or {})
    repository: RepositoryRunFacts = {"ref": scope.get("ref"), "commit": connector.commit}
    empty = bool(getattr(connector, "repository_empty", False))
    if empty:
        repository["empty"] = True
    run.report = {**dict(run.report or {}), "repository": repository}
    if run.state == RUN_STATE_COMPLETED and empty:
        if scope.get(HEAD_COMMIT):
            await retire_unseen(db, connector_id=connector_id, head_commit=_NO_COMMIT)  # every row: none is at it
            row.scope = {key: value for key, value in scope.items() if key != HEAD_COMMIT}
    elif run.state == RUN_STATE_COMPLETED and connector.commit is not None:
        await mark_seen(db, connector_id=connector_id, commit_sha=connector.commit, paths=connector.item_paths)
        await retire_unseen(db, connector_id=connector_id, head_commit=connector.commit)
        row.scope = {**scope, HEAD_COMMIT: connector.commit, HEAD_DIRTY: False}
    await db.commit()


__all__ = ["git_connector", "record_git_run"]
