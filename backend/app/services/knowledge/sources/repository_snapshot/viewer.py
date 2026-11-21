"""The platform source viewer for a repository file at a commit (the non-host citation target).

A repository file without a faithful host link is cited as
``<origin>/api/v1/workspaces/<ws>/knowledge/repositories/<key>/blob/<commit>/<path>?blob=<sha>``.
That covers a dirty or unpushed local snapshot and any host that is not a known one. This module
answers such a link for a reader of the Workspace from the ledger: the cited revision and its spans
(redacted text).

- **With ``blob``**: the path's recorded blob (``knowledge_code_file_blobs``), current or
  superseded. A link to an older commit keeps opening exactly the content it cited.
- **Without ``blob``**: the path's current row, if ``commit`` is a commit the
  row recorded (indexed at, or last seen at).
  - Otherwise: :class:`BlobSuperseded`, naming the current commit. The index keeps blobs, not
    trees, so a bare commit it no longer resolves is said so and never guessed.
  - An unknown source or path, or an unknown blob: ``None`` (404).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.code.repository_paths import path_digest
from app.services.knowledge.code.repository_reads import indexed_blob

from .....models.project.knowledge_code_files import KnowledgeCodeFile
from .....models.project.knowledge_evidence import KnowledgeEvidenceSpan
from ...access.authorization import AuthorizedWorkspace
from .binding import repository_connector, valid_commit

MAX_VIEWER_SPANS = 400
STATE_BLOB_SUPERSEDED = "blob_superseded"


@dataclass(frozen=True, slots=True)
class RepositoryFileView:
    path: str
    commit: str
    blob_sha: str
    language: str | None
    source_id: str | None
    revision_id: str | None
    current: bool
    spans: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class BlobSuperseded:
    path: str
    current_commit: str
    current_blob: str


async def _spans(db: AsyncSession, project_id: str, revision_id: str | None) -> tuple[tuple[int, str], ...]:
    if not revision_id:
        return ()
    found = await db.execute(
        select(KnowledgeEvidenceSpan.span_ordinal, KnowledgeEvidenceSpan.text)
        .where(KnowledgeEvidenceSpan.revision_id == revision_id, KnowledgeEvidenceSpan.project_id == project_id)
        .order_by(KnowledgeEvidenceSpan.span_ordinal)
        .limit(MAX_VIEWER_SPANS)
    )
    return tuple((int(ordinal), str(text)) for ordinal, text in found.all())


async def view_repository_file(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    *,
    connector_key: str,
    commit: str,
    path: str,
    blob_sha: str | None = None,
) -> RepositoryFileView | BlobSuperseded | None:
    connector = await repository_connector(db, authorized.project_id, connector_key)
    if connector is None or valid_commit(commit) is None:
        return None
    row = (
        await db.execute(
            select(KnowledgeCodeFile).where(
                KnowledgeCodeFile.connector_id == connector.id,
                KnowledgeCodeFile.project_id == authorized.project_id,
                KnowledgeCodeFile.path_digest == path_digest(path),
            )
        )
    ).scalar_one_or_none()
    if blob_sha is not None:
        if valid_commit(blob_sha) is None:
            return None
        recorded = await indexed_blob(db, connector_id=connector.id, path=path, blob_sha=blob_sha)
        if recorded is None or recorded.project_id != authorized.project_id:
            return None
        current = row is not None and row.blob_sha == blob_sha
        return RepositoryFileView(
            path=recorded.path, commit=commit, blob_sha=recorded.blob_sha, language=row.language if row else None,
            source_id=recorded.source_id, revision_id=recorded.revision_id, current=current,
            spans=await _spans(db, authorized.project_id, recorded.revision_id),
        )
    if row is None:
        return None
    if commit not in {row.commit_sha, row.last_seen_commit}:
        return BlobSuperseded(path=row.path, current_commit=row.last_seen_commit, current_blob=row.blob_sha)
    return RepositoryFileView(
        path=row.path, commit=commit, blob_sha=row.blob_sha, language=row.language, source_id=row.source_id,
        revision_id=row.revision_id, current=True, spans=await _spans(db, authorized.project_id, row.revision_id),
    )


__all__ = ["STATE_BLOB_SUPERSEDED", "BlobSuperseded", "RepositoryFileView", "view_repository_file"]
