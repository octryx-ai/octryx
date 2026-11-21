"""What a ``git_repository`` run adds to the generic Source Sync run.

- Only ``remote_git`` connectors run here: a ``local_snapshot`` connector has nothing to fetch, its
  files arrive with an upload, so a run of it is refused with ``snapshot_upload_required``.
- The run report gets ``repository``: the configured ``ref`` and the ``commit`` this run listed (null
  when the run failed before resolving one).
- A **completed** pass records its commit as the connector's run state (``head_commit``, with
  ``head_dirty`` false): the commit every file the connector now serves was listed at, which code
  impact reads. A stopped pass records nothing, so ``head_commit`` never names a half-synced commit.
- The same completion moves the repository file index to that commit (``code/repository_index``):
  every item of the commit is marked seen (unchanged files were not re-ingested, so their rows only
  move commits), and the rows of paths the commit no longer lists are deleted. Their ledger sources
  were already retired by the runner's reconcile, which owns tombstones.
- A completed pass over a repository **without any commit** (``repository_empty``) records
  ``repository.empty`` in the report and no commit: ``head_commit`` is cleared and the file index emptied (a
  repository that lost every branch serves nothing any more; the runner already retired its sources).
"""

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

_NO_COMMIT = "0" * 40  # Git's null object id: no indexed file was ever seen at it


def git_connector(
    row: KnowledgeSourceConnector, *, transport=None, connection=None, clone_reader=None
) -> GitRepositoryConnector:
    """``clone_reader``: tests only (a Git runner without network); else built from the connection's credential."""
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
    repository = {"ref": scope.get("ref"), "commit": connector.commit}
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
