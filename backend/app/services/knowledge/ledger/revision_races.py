"""Ledger reads behind revision registration and the classification of its insert races. Retries are decided from
committed ledger state, never from driver error text."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevision

# Bounded: each retry is one recomputed ordinal against live contention. The bound
# exists so contention can never turn into an unbounded loop inside a request.
MAX_ORDINAL_RETRIES = 3

# Which insert lost the race; the only thing carried out of an ``IntegrityError``.
_STAGE_SOURCE = "source"
_STAGE_REVISION = "revision"


class _RevisionInsertConflictError(Exception):
    # Carries nothing from the database error, so classification never reads constraint or statement text.
    def __init__(self, *, stage: str, attempted_ordinal: int | None) -> None:
        super().__init__(stage)
        self.stage = stage
        self.attempted_ordinal = attempted_ordinal


@dataclass(frozen=True, slots=True)
class RegisteredRevision:
    source_id: str
    revision_id: str
    revision_ordinal: int
    content_sha256: str
    span_count: int
    created: bool


async def _source_id(db: AsyncSession, project_id: str, source_key: str) -> str | None:
    statement = select(KnowledgeEvidenceSource.id).where(
        KnowledgeEvidenceSource.project_id == project_id,
        KnowledgeEvidenceSource.source_key == source_key,
    )
    return (await db.execute(statement)).scalar_one_or_none()


async def _existing_revision(
    db: AsyncSession, project_id: str, source_id: str, digest: str
) -> RegisteredRevision | None:
    statement = select(
        KnowledgeSourceRevision.id,
        KnowledgeSourceRevision.revision_ordinal,
        KnowledgeSourceRevision.span_count,
    ).where(
        KnowledgeSourceRevision.project_id == project_id,
        KnowledgeSourceRevision.source_id == source_id,
        KnowledgeSourceRevision.content_sha256 == digest,
    )
    row = (await db.execute(statement)).first()
    if row is None:
        return None
    return RegisteredRevision(
        source_id=source_id,
        revision_id=row[0],
        revision_ordinal=row[1],
        content_sha256=digest,
        span_count=row[2],
        created=False,
    )


async def _ordinal_taken(db: AsyncSession, project_id: str, source_id: str, ordinal: int) -> bool:
    statement = select(KnowledgeSourceRevision.id).where(
        KnowledgeSourceRevision.project_id == project_id,
        KnowledgeSourceRevision.source_id == source_id,
        KnowledgeSourceRevision.revision_ordinal == ordinal,
    )
    return (await db.execute(statement)).first() is not None


async def _is_retryable_race(
    db: AsyncSession, project_id: str, source_key: str, digest: str, conflict: _RevisionInsertConflictError
) -> bool:
    # A race is only a race if somebody else's row is now there; anything else is refused, not retried.
    source_id = await _source_id(db, project_id, source_key)
    if source_id is None:
        # The source is still absent, so no concurrent ingestion won anything.
        return False
    if conflict.stage == _STAGE_SOURCE:
        # The source row exists although this insert created it and failed: another
        # ingestion registered the same source key first.
        return True
    if await _existing_revision(db, project_id, source_id, digest) is not None:
        return True  # same-digest winner; the next iteration adopts it
    if conflict.attempted_ordinal is None:  # pragma: no cover - set for every revision insert
        return False
    # Different bytes, same computed ordinal: recompute and retry.
    return await _ordinal_taken(db, project_id, source_id, conflict.attempted_ordinal)


async def _next_ordinal(db: AsyncSession, project_id: str, source_id: str) -> int:
    # Read-then-insert on purpose: the unique constraint arbitrates and ``register_revision`` retries the loser.
    highest = (
        await db.execute(
            select(func.max(KnowledgeSourceRevision.revision_ordinal)).where(
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeSourceRevision.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    return int(highest or 0) + 1
