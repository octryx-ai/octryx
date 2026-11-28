"""The code index of a ``git_repository`` source: write one file, read a repository. Every function runs in the caller's
transaction and never commits."""

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
