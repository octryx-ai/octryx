"""Ordering subject versions and picking the current revisions of a product."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeRevisionScope,
    KnowledgeSourceRevision,
)

MAX_SCOPED_REVISIONS = 500


def version_key(version: str) -> tuple[int, ...]:
    if version[:1] in ("v", "V") and version[1:2].isdigit():
        version = version[1:]
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def in_range(version: str | None, *, after: str | None, through: str) -> bool:
    if not version:
        return False
    key = version_key(version)
    upper = version_key(through)
    if key[: len(upper)] > upper:
        return False
    if after is None:
        return True
    lower = version_key(after)
    return key[: len(lower)] > lower


def is_empty_range(after: str, through: str) -> bool:
    lower = version_key(after)
    return version_key(through)[: len(lower)] <= lower


@dataclass(frozen=True, slots=True)
class ScopedRevision:
    revision_id: str
    version: str | None


async def current_revisions_of(db: AsyncSession, project_id: str, product: str) -> list[ScopedRevision]:
    rows = await db.execute(
        select(KnowledgeSourceRevision.id, KnowledgeRevisionScope.products, KnowledgeRevisionScope.version)
        .join(KnowledgeRevisionScope, KnowledgeRevisionScope.revision_id == KnowledgeSourceRevision.id)
        .where(
            KnowledgeSourceRevision.project_id == project_id,
            KnowledgeRevisionScope.project_id == project_id,
            KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
        )
        .limit(MAX_SCOPED_REVISIONS)
    )
    return [ScopedRevision(row[0], row[2]) for row in rows.all() if product in (row[1] or ())]


__all__ = ["ScopedRevision", "current_revisions_of", "in_range", "is_empty_range", "version_key"]
