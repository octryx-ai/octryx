"""Revision lifecycle of a Knowledge source: which revision it says, and which one is served.

A source's head carries two pointers:

- ``wanted`` follows the latest upload: a new revision, or the exact bytes of an earlier one
  again. It is null once the source is tombstoned.
- ``current`` is the one ``projected`` revision, which default retrieval serves.

Projection settles the difference. When a revision's projection completes, it becomes current
only if it is still wanted; the previous current revision, or the finished one when it is no
longer wanted, is superseded or tombstoned, and a ``retire_revision`` obligation removes its
spans from the Workspace database. The ledger keeps every revision and span as history.

Every function here runs inside the caller's transaction and never commits. The head row is
read ``FOR UPDATE`` on PostgreSQL, so two projections of one source settle one after the other.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EMBED_REVISION,
    OUTBOX_OPERATION_PROJECT_REVISION,
    REVISION_STATE_PROJECTED,
    REVISION_STATE_REGISTERED,
    REVISION_STATE_SUPERSEDED,
    REVISION_STATE_TOMBSTONED,
    KnowledgeEvidenceSource,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....time_utils import utc_now
from ..access.authorization import AuthorizedWorkspace
from .errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError

# The outbox obligations live in their own module; callers keep importing them from here.
from .obligations import _ensure_obligation, _reopen, ensure_retirement

REMOVE_SOURCE_AUDIT_ACTION = "knowledge.source.remove"

# States whose spans may still be in the Workspace database and must be retired.
_RETIRED_STATES = frozenset({REVISION_STATE_SUPERSEDED, REVISION_STATE_TOMBSTONED})


async def _revision(db: AsyncSession, project_id: str, revision_id: str) -> tuple[str, str]:
    """``(source_id, state)`` of one revision of this Workspace."""
    row = (
        await db.execute(
            select(KnowledgeSourceRevision.source_id, KnowledgeSourceRevision.state).where(
                KnowledgeSourceRevision.id == revision_id,
                KnowledgeSourceRevision.project_id == project_id,
            )
        )
    ).first()
    if row is None:
        raise EvidenceRecordNotFoundError()
    return row[0], row[1]


async def _set_state(db: AsyncSession, project_id: str, revision_id: str, state: str) -> None:
    values: dict[str, object] = {"state": state}
    if state == REVISION_STATE_PROJECTED:
        values["projected_at"] = utc_now()
    result = await db.execute(
        update(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.id == revision_id, KnowledgeSourceRevision.project_id == project_id)
        .values(**values)
    )
    if result.rowcount != 1:
        raise EvidenceLedgerContractError()


async def load_head(db: AsyncSession, project_id: str, source_id: str) -> KnowledgeSourceHead:
    """The source's head row, locked for this transaction. Every source gets its head with its first revision
    (:func:`create_head`), so a missing head is a ledger contract violation."""
    head = (
        await db.execute(
            select(KnowledgeSourceHead)
            .where(KnowledgeSourceHead.source_id == source_id, KnowledgeSourceHead.project_id == project_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if head is None:
        raise EvidenceLedgerContractError()
    return head


def create_head(db: AsyncSession, *, project_id: str, source_id: str, revision_id: str) -> None:
    """The head of a source created in this very transaction: its first revision is what it says.

    No lock and no savepoint: until this transaction commits, no other one can see the source.
    """
    db.add(KnowledgeSourceHead(source_id=source_id, project_id=project_id, wanted_revision_id=revision_id))


async def want_revision(db: AsyncSession, *, project_id: str, source_id: str, revision_id: str) -> None:
    """The latest upload of the source is ``revision_id``: a new revision, or its exact bytes again.

    A superseded or tombstoned revision is registered again and its projection reopened, so
    re-uploading an earlier version, or a removed source, brings it back.
    """
    head = await load_head(db, project_id, source_id)
    head.wanted_revision_id = revision_id
    _, state = await _revision(db, project_id, revision_id)
    if state in _RETIRED_STATES:
        await _set_state(db, project_id, revision_id, REVISION_STATE_REGISTERED)
        if not await _reopen(db, project_id, revision_id, OUTBOX_OPERATION_PROJECT_REVISION):
            raise EvidenceLedgerContractError()


async def settle_projection(db: AsyncSession, *, project_id: str, revision_id: str, embed: bool = False) -> str:
    """The projection of ``revision_id`` has completed: decide what it is now, and return that state.

    With ``embed`` (an embedding space is configured), a revision that becomes current also owes
    its vectors; a superseded or tombstoned one never does.
    """
    source_id, _ = await _revision(db, project_id, revision_id)
    head = await load_head(db, project_id, source_id)
    if head.wanted_revision_id != revision_id:
        # Not what the source says any more: a newer upload, another version again, or removal.
        final = REVISION_STATE_TOMBSTONED if head.wanted_revision_id is None else REVISION_STATE_SUPERSEDED
        await _set_state(db, project_id, revision_id, final)
        await ensure_retirement(db, project_id, revision_id)
        return final
    previous = head.current_revision_id
    await _set_state(db, project_id, revision_id, REVISION_STATE_PROJECTED)
    head.current_revision_id = revision_id
    if embed and previous != revision_id:
        # A re-projection of the current revision (a new ACL marker) keeps its vectors:
        # the span upsert never touches them, so they are not owed again.
        await _ensure_obligation(db, project_id, revision_id, OUTBOX_OPERATION_EMBED_REVISION)
    if previous is not None and previous != revision_id:
        await _set_state(db, project_id, previous, REVISION_STATE_SUPERSEDED)
        await ensure_retirement(db, project_id, previous)
    return REVISION_STATE_PROJECTED


async def tombstone_source(db: AsyncSession, *, project_id: str, source_id: str) -> int:
    """Remove a source from the served Knowledge. Returns the number of revisions tombstoned.

    Every revision is tombstoned and owes retirement, including one still being projected:
    its completion settles to ``tombstoned`` as well, and retires what it wrote meanwhile.
    """
    head = await load_head(db, project_id, source_id)
    head.wanted_revision_id = None
    head.current_revision_id = None
    rows = (
        await db.execute(
            select(KnowledgeSourceRevision.id, KnowledgeSourceRevision.state).where(
                KnowledgeSourceRevision.project_id == project_id, KnowledgeSourceRevision.source_id == source_id
            )
        )
    ).all()
    tombstoned = 0
    for revision_id, state in rows:
        if state != REVISION_STATE_TOMBSTONED:
            await _set_state(db, project_id, revision_id, REVISION_STATE_TOMBSTONED)
            tombstoned += 1
        await ensure_retirement(db, project_id, revision_id)
    return tombstoned


async def remove_source(db: AsyncSession, *, authorized: AuthorizedWorkspace, source_id: str, actor_id: str) -> int:
    """Tombstone one source of this Workspace, audit it, and commit. Returns the revisions tombstoned.

    A source of another Workspace is absent, not forbidden, so it cannot be probed.
    """
    if type(authorized) is not AuthorizedWorkspace or type(source_id) is not str:
        raise EvidenceLedgerContractError()
    owned = (
        await db.execute(
            select(KnowledgeEvidenceSource.id).where(
                KnowledgeEvidenceSource.id == source_id,
                KnowledgeEvidenceSource.project_id == authorized.project_id,
            )
        )
    ).scalar_one_or_none()
    if owned is None:
        raise EvidenceRecordNotFoundError()
    tombstoned = await tombstone_source(db, project_id=authorized.project_id, source_id=source_id)
    db.add(
        AuditLog(
            user_id=actor_id,
            action=REMOVE_SOURCE_AUDIT_ACTION,
            resource_type="knowledge_source",
            resource_id=source_id,
            details={"workspace_id": authorized.project_id, "tombstoned_revisions": tombstoned},
        )
    )
    await db.commit()
    return tombstoned


EMBEDDING_BACKFILL_AUDIT_ACTION = "knowledge.embedding.backfill"


async def backfill_embeddings(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, actor_id: str, space_key: str
) -> int:
    """Owe vectors for every current revision of this Workspace, audit it, and commit.

    For sources projected before an embedding space was configured, and after the Instance
    switches space: each space has its own property, so this fills the configured one without
    touching another. Completed obligations are reopened; pending ones are left alone.
    """
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    current = (
        (
            await db.execute(
                select(KnowledgeSourceRevision.id).where(
                    KnowledgeSourceRevision.project_id == authorized.project_id,
                    KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
                )
            )
        )
        .scalars()
        .all()
    )
    for revision_id in current:
        await _ensure_obligation(db, authorized.project_id, revision_id, OUTBOX_OPERATION_EMBED_REVISION)
    db.add(
        AuditLog(
            user_id=actor_id,
            action=EMBEDDING_BACKFILL_AUDIT_ACTION,
            resource_type="workspace",
            resource_id=authorized.project_id,
            details={"embedding_space": space_key, "revisions": len(current)},
        )
    )
    await db.commit()
    return len(current)


__all__ = [
    "EMBEDDING_BACKFILL_AUDIT_ACTION",
    "REMOVE_SOURCE_AUDIT_ACTION",
    "backfill_embeddings",
    "create_head",
    "load_head",
    "remove_source",
    "settle_projection",
    "tombstone_source",
    "want_revision",
]
