"""The code index of a ``git_repository`` source: write one file, read a repository (code module).

The one writer for both fetch modes (C-MCP ``local_snapshot`` upload, K7 ``remote_git`` fetch):

- :func:`upsert_file` records one tracked file at one commit. It derives the code elements from the
  file text itself (``scan.elements_of_text``), so the two modes cannot disagree on them. An
  unchanged blob keeps its row and its elements; only the commits move.
- :func:`mark_seen` moves ``last_seen_commit`` of the unchanged files of a tree listing to the new
  head in one statement, so an incremental snapshot does not rewrite every row.
- :func:`retire_unseen` deletes the rows of paths that the head commit no longer lists and returns
  them. Retiring their ledger sources is the sync owner's job (``KnowledgeSourceSyncItem``).

The reader :func:`load_repository_index` answers the elements of every file seen at the
repository's head commit, bounded, for ``knowledge_code_impact``.

Every function runs in the caller's transaction and never commits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_code_files import KnowledgeCodeFile, KnowledgeCodeFileBlob
from ..ledger.errors import EvidenceLedgerContractError
from .repository_paths import MAX_ELEMENTS_PER_FILE, _language, _sha1, path_digest, validate_repository_path
from .scan import CodeElement, elements_of_text, is_scanned_file


@dataclass(frozen=True, slots=True)
class CodeFileRecord:
    """One indexed file as written; ``changed`` is False when the blob was already indexed."""

    path: str
    language: str | None
    blob_sha: str
    commit_sha: str
    source_id: str | None
    revision_id: str | None
    element_count: int
    changed: bool


def _encoded(elements: list[CodeElement]) -> list[list[object]]:
    return [[item.kind, item.value, item.line, item.detail] for item in elements[:MAX_ELEMENTS_PER_FILE]]


async def upsert_file(
    db: AsyncSession,
    *,
    project_id: str,
    connector_id: str,
    path: str,
    blob_sha: str,
    commit_sha: str,
    language: str | None,
    source_id: str | None,
    revision_id: str | None,
    text: str | None,
) -> CodeFileRecord:
    """Record ``path`` at ``commit_sha`` with the blob ``blob_sha``; flushes only.

    ``text`` is the file's decoded text (after the caller's redaction, which preserves lines), or
    ``None`` for a file that is tracked but not indexed (binary, too large): it then has no elements.
    The same ``blob_sha`` as recorded keeps the row's elements and source; only the commits move.
    """
    path = validate_repository_path(path)
    blob_sha = _sha1(blob_sha)
    commit_sha = _sha1(commit_sha)
    language = _language(language)
    digest = path_digest(path)
    row = (
        await db.execute(
            select(KnowledgeCodeFile).where(
                KnowledgeCodeFile.connector_id == connector_id, KnowledgeCodeFile.path_digest == digest
            )
        )
    ).scalar_one_or_none()
    if row is not None and row.project_id != project_id:
        raise EvidenceLedgerContractError()
    if row is not None and row.blob_sha == blob_sha:
        row.last_seen_commit = commit_sha
        if source_id is not None:
            row.source_id, row.revision_id = source_id, revision_id
            await _remember_blob(db, row=row, source_id=source_id, revision_id=revision_id, commit_sha=commit_sha)
        await db.flush()
        return _record(row, changed=False)
    elements = elements_of_text(path, text) if text is not None and is_scanned_file(path) else []
    if row is None:
        row = KnowledgeCodeFile(project_id=project_id, connector_id=connector_id, path=path, path_digest=digest)
        db.add(row)
    row.language = language
    row.blob_sha = blob_sha
    row.commit_sha = commit_sha
    row.last_seen_commit = commit_sha
    row.source_id = source_id
    row.revision_id = revision_id
    row.elements = _encoded(elements)
    row.element_count = len(row.elements)
    await db.flush()
    await _remember_blob(db, row=row, source_id=source_id, revision_id=revision_id, commit_sha=commit_sha)
    return _record(row, changed=True)


async def _remember_blob(
    db: AsyncSession, *, row: KnowledgeCodeFile, source_id: str | None, revision_id: str | None, commit_sha: str
) -> None:
    """Keep the path's blob with its revision, so links to this blob work after the path moves on."""
    if revision_id is None:
        return
    known = (
        await db.execute(
            select(KnowledgeCodeFileBlob).where(
                KnowledgeCodeFileBlob.connector_id == row.connector_id,
                KnowledgeCodeFileBlob.path_digest == row.path_digest,
                KnowledgeCodeFileBlob.blob_sha == row.blob_sha,
            )
        )
    ).scalar_one_or_none()
    if known is None:
        db.add(
            KnowledgeCodeFileBlob(
                project_id=row.project_id,
                connector_id=row.connector_id,
                path_digest=row.path_digest,
                path=row.path,
                blob_sha=row.blob_sha,
                first_commit=commit_sha,
                source_id=source_id,
                revision_id=revision_id,
            )
        )
    elif known.revision_id is None:
        known.source_id, known.revision_id = source_id, revision_id
    await db.flush()


def _record(row: KnowledgeCodeFile, *, changed: bool) -> CodeFileRecord:
    return CodeFileRecord(
        path=row.path,
        language=row.language,
        blob_sha=row.blob_sha,
        commit_sha=row.commit_sha,
        source_id=row.source_id,
        revision_id=row.revision_id,
        element_count=int(row.element_count or 0),
        changed=changed,
    )


async def mark_seen(db: AsyncSession, *, connector_id: str, commit_sha: str, paths: Iterable[str]) -> int:
    """Move ``last_seen_commit`` of already indexed, unchanged ``paths`` to ``commit_sha``."""
    commit_sha = _sha1(commit_sha)
    digests = [path_digest(path) for path in paths]
    moved = 0
    for start in range(0, len(digests), 500):
        result = await db.execute(
            update(KnowledgeCodeFile)
            .where(
                KnowledgeCodeFile.connector_id == connector_id,
                KnowledgeCodeFile.path_digest.in_(digests[start : start + 500]),
            )
            .values(last_seen_commit=commit_sha)
        )
        moved += int(result.rowcount or 0)
    return moved


async def retire_unseen(db: AsyncSession, *, connector_id: str, head_commit: str) -> list[tuple[str, str | None]]:
    """Delete the rows the head commit no longer lists; ``[(path, source_id)]`` of the deleted rows."""
    head_commit = _sha1(head_commit)
    rows = (
        await db.execute(
            select(KnowledgeCodeFile.id, KnowledgeCodeFile.path, KnowledgeCodeFile.source_id).where(
                KnowledgeCodeFile.connector_id == connector_id, KnowledgeCodeFile.last_seen_commit != head_commit
            )
        )
    ).all()
    if rows:
        await db.execute(delete(KnowledgeCodeFile).where(KnowledgeCodeFile.id.in_([row.id for row in rows])))
    return [(row.path, row.source_id) for row in rows]


__all__ = [
    "CodeFileRecord",
    "mark_seen",
    "retire_unseen",
    "upsert_file",
]
