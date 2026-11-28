"""Owe the knowledge-graph extraction of a product's current revisions. It never starts by itself: an author asks for it
explicitly."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.ledger.obligations import ensure_graph_extraction

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EXTRACT_GRAPH,
    OUTBOX_STATE_APPLIED,
    KnowledgeProjectionOutboxEntry,
)
from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import EvidenceGraphNotConfiguredError, InvalidEvidenceRequestError
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from .change_types import CHANGE_RECORDS_PROFILE, CURRENT_PROFILES
from .profile_migration import episodes_by_profile, revisions_with_stale_episodes
from .versions import current_revisions_of, in_range, is_empty_range

MAX_REVISIONS_PER_REQUEST = 100


@dataclass(frozen=True, slots=True)
class GraphStatus:
    episodes: int
    pending_revisions: int
    # Episodes per extraction profile; any profile outside ``CURRENT_PROFILES`` is still to be purged.
    profiles: dict[str, int]
    stale_episodes: int
    current_profile: str = CHANGE_RECORDS_PROFILE


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    # Every revision now owing extraction, of the scope and of the stale-profile convergence.
    revisions_owed: int
    # Of those, the revisions outside the requested scope that still held an earlier profile.
    stale_revisions_owed: int


def _in_scope(version: str | None, *, exact: str | None, after: str | None, through: str | None) -> bool:
    if exact is not None:
        return version == exact
    if through is not None:
        return in_range(version, after=after, through=through)
    return True


async def request_graph_extraction(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    product: object,
    version: object = None,
    from_version: object = None,
    to_version: object = None,
) -> ExtractionRequest:
    products = normalize_products(product)
    exact = normalize_version(version)
    after = normalize_version(from_version)
    through = normalize_version(to_version)
    if len(products) != 1:
        raise InvalidEvidenceRequestError()
    # One version or one range, never both; a range needs its upper bound and must not be empty.
    if exact is not None and (after is not None or through is not None):
        raise InvalidEvidenceRequestError()
    if after is not None and (through is None or is_empty_range(after, through)):
        raise InvalidEvidenceRequestError()
    if runtime.embedding is None:
        raise EvidenceGraphNotConfiguredError()
    current = await current_revisions_of(db, authorized.project_id, products[0])
    scoped = {
        item.revision_id for item in current if _in_scope(item.version, exact=exact, after=after, through=through)
    }
    stale = await revisions_with_stale_episodes(
        db, authorized.project_id, [item.revision_id for item in current if item.revision_id not in scoped]
    )
    owed = sorted(scoped | stale)
    if len(owed) > MAX_REVISIONS_PER_REQUEST:
        raise InvalidEvidenceRequestError()
    for revision_id in owed:
        await ensure_graph_extraction(db, authorized.project_id, revision_id)
    await db.commit()
    return ExtractionRequest(revisions_owed=len(owed), stale_revisions_owed=len(stale))


async def graph_status(db: AsyncSession, project_id: str) -> GraphStatus:
    profiles = await episodes_by_profile(db, project_id)
    pending = (
        await db.execute(
            select(func.count(KnowledgeProjectionOutboxEntry.id)).where(
                KnowledgeProjectionOutboxEntry.project_id == project_id,
                KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_EXTRACT_GRAPH,
                KnowledgeProjectionOutboxEntry.state != OUTBOX_STATE_APPLIED,
            )
        )
    ).scalar_one()
    stale = sum(count for profile, count in profiles.items() if profile not in CURRENT_PROFILES)
    return GraphStatus(
        episodes=sum(profiles.values()), pending_revisions=int(pending), profiles=profiles, stale_episodes=stale
    )


__all__ = ["ExtractionRequest", "GraphStatus", "graph_status", "request_graph_extraction"]
