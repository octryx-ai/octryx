"""Reads of the repository code index: recorded blobs and the elements at a head commit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_code_files import KnowledgeCodeFile, KnowledgeCodeFileBlob
from .repository_paths import _sha1, path_digest
from .scan import MAX_ELEMENTS, CodeElement


@dataclass(frozen=True, slots=True)
class RepositoryCodeIndex:
    connector_id: str
    head_commit: str
    file_count: int
    elements: tuple[CodeElement, ...]
    truncated: bool


async def indexed_blob(
    db: AsyncSession, *, connector_id: str, path: str, blob_sha: str
) -> KnowledgeCodeFileBlob | None:
    return (
        await db.execute(
            select(KnowledgeCodeFileBlob).where(
                KnowledgeCodeFileBlob.connector_id == connector_id,
                KnowledgeCodeFileBlob.path_digest == path_digest(path),
                KnowledgeCodeFileBlob.blob_sha == blob_sha,
            )
        )
    ).scalar_one_or_none()


async def indexed_blobs(db: AsyncSession, *, connector_id: str, paths: Iterable[str]) -> dict[str, str]:
    by_digest = {path_digest(path): path for path in paths}
    if not by_digest:
        return {}
    found: dict[str, str] = {}
    digests = list(by_digest)
    for start in range(0, len(digests), 500):
        rows = await db.execute(
            select(KnowledgeCodeFile.path_digest, KnowledgeCodeFile.blob_sha).where(
                KnowledgeCodeFile.connector_id == connector_id,
                KnowledgeCodeFile.path_digest.in_(digests[start : start + 500]),
            )
        )
        found.update({by_digest[digest]: blob for digest, blob in rows.all()})
    return found


async def load_repository_index(db: AsyncSession, *, connector_id: str, head_commit: str) -> RepositoryCodeIndex:
    head_commit = _sha1(head_commit)
    rows = (
        await db.execute(
            select(KnowledgeCodeFile.path, KnowledgeCodeFile.elements)
            .where(KnowledgeCodeFile.connector_id == connector_id, KnowledgeCodeFile.last_seen_commit == head_commit)
            .order_by(KnowledgeCodeFile.path)
        )
    ).all()
    elements: list[CodeElement] = []
    truncated = False
    for path, encoded in rows:
        for item in encoded or []:
            if len(elements) >= MAX_ELEMENTS:
                truncated = True
                break
            kind, value, line, detail = item
            elements.append(CodeElement(str(kind), str(value), path, int(line), str(detail or "")))
    return RepositoryCodeIndex(
        connector_id=connector_id,
        head_commit=head_commit,
        file_count=len(rows),
        elements=tuple(elements),
        truncated=truncated,
    )
