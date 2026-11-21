"""What changed in a product between two versions, as cited graph facts.

``knowledge_changes`` answers "what changed from Spring Boot 3.5 to 4.0" from the knowledge graph,
not from a text search. It proceeds in five steps:

1. Pick the product's current revisions whose subject version lies in ``(from_version,
   to_version]``. This uses the ledger's product and version scope, which the extraction recorded
   per revision; the model never guesses a version.
2. Take the extraction episodes of those revisions from ``knowledge_graph_episodes``.
3. Read the facts extracted from those episodes, from the Workspace's graph only. With a
   ``query``, the facts are ranked by the graph's full-text and vector search and fused by
   reciprocal rank; without one, they are listed in document order.
4. Resolve each fact's first supporting episode back through PostgreSQL to its span, citation,
   section and origin link. A fact that does not resolve to a current revision is dropped.
5. Return the bounded result with an explicit state.

States:

- ``not_extracted``: the range has sources but no extracted episodes, so the graph was never asked.
- ``no_sources``: nothing in the range.

Neither state is ever an empty "no changes".
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_temporal import KnowledgeGraphEpisode
from ..access.authorization import AuthorizedWorkspace
from ..embedding.port import EmbeddingError, EmbeddingState
from ..embedding.selection import admit_space
from ..ledger.errors import (
    EmbeddingSpaceDeniedError,
    EvidenceGraphNotConfiguredError,
    EvidenceStoreNotConfiguredError,
    InvalidEvidenceRequestError,
)
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from .change_ranking import distinct, is_product_level, rank_tier, source_roles
from .changes_facts import ChangeFact, ChangesResult, _cited, ranked_edge_uuids
from .postgres_graph import PostgresGraphDriver
from .versions import current_revisions_of, in_range, is_empty_range, version_key

logger = logging.getLogger(__name__)

MAX_FACTS = 200
# A page lists what blocks an upgrade first, then what should be revisited, then what is new.
_TIERS = (
    ("REQUIRES", "REMOVED", "RENAMED", "REPLACED_BY", "MOVED_TO"),
    ("DEPRECATED", "DEFAULT_CHANGED"),
    ("INTRODUCED",),
)
_KIND_TIER = {kind: tier for tier, kinds in enumerate(_TIERS) for kind in kinds}
# The order a page lists kinds in: what blocks an upgrade first, new capabilities last.
_KIND_ORDER = {
    kind: index
    for index, kind in enumerate(
        ("REQUIRES", "REMOVED", "RENAMED", "REPLACED_BY", "MOVED_TO", "DEPRECATED", "DEFAULT_CHANGED", "INTRODUCED")
    )
}


def _kind_rank(kind: str) -> int:
    return _KIND_ORDER.get(kind, len(_KIND_ORDER))


# The impact join reads every actionable fact of a range, not one page of it.
MAX_IMPACT_FACTS = 2000
# One page fits the tool-result budget the model sees (about 2200 tokens), sources listed once.
DEFAULT_FACTS = 20
STATE_OK = "ok"
STATE_NOT_EXTRACTED = "not_extracted"
STATE_NO_SOURCES = "no_sources"

_FACTS_MATCH = (
    "MATCH (a:Entity)-[e:RELATES_TO]->(b:Entity) "
    "WHERE e.group_id = $group AND size([episode IN e.episodes WHERE episode IN $episodes]) > 0 "
)
_FACTS_RETURN = (
    "RETURN e.uuid AS uuid, e.name AS relation, e.fact AS fact, e.episodes AS episodes, "
    "e.created_at AS created_at, a.name AS source, b.name AS target "
    "LIMIT $limit"
)
_FACTS = _FACTS_MATCH + _FACTS_RETURN
_FACTS_OF_KINDS = _FACTS_MATCH + "AND e.name IN $kinds " + _FACTS_RETURN


async def knowledge_changes(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    product: object,
    to_version: object,
    from_version: object = None,
    query: object = None,
    limit: object = None,
    kinds: frozenset[str] | None = None,
    max_facts: int = MAX_FACTS,
) -> ChangesResult:
    """The cited facts that changed in ``product`` from ``from_version`` (exclusive) to ``to_version``."""
    product_key, through, after, bounded = _checked_request(
        runtime, product, to_version, from_version, query, limit, max_facts
    )
    revisions = [
        item
        for item in await current_revisions_of(db, authorized.project_id, product_key)
        if in_range(item.version, after=after, through=through)
    ]
    versions = tuple(sorted({item.version for item in revisions if item.version}, key=version_key))

    def result(state: str, facts: tuple[ChangeFact, ...] = (), episodes: int = 0, counts=None) -> ChangesResult:
        return ChangesResult(state, product_key, after, through, versions, facts, episodes, dict(counts or {}))

    if not revisions:
        return result(STATE_NO_SOURCES)
    version_of = {item.revision_id: item.version for item in revisions}
    episode_rows = await _episode_rows(db, authorized.project_id, list(version_of))
    if not episode_rows:
        return result(STATE_NOT_EXTRACTED)
    episode_span = {row[0]: (row[1], int(row[2])) for row in episode_rows}
    if query is not None:
        await _admit_query(db, runtime, authorized)
    rows, order = await _read_rows(runtime, authorized, product_key, episode_span, query, kinds, max_facts)

    if query is not None:
        facts = await _cited(db, authorized, order[:bounded], rows, episode_span, version_of)
        return result(STATE_OK, tuple(facts), len(episode_rows), Counter(item.relation for item in facts))
    paged, counts = await _whole_range_page(db, authorized, product_key, order, rows, episode_span, version_of)
    return result(STATE_OK, tuple(paged[:bounded]), len(episode_rows), counts)


def _checked_request(
    runtime: EvidenceRuntime,
    product: object,
    to_version: object,
    from_version: object,
    query: object,
    limit: object,
    max_facts: int,
) -> tuple[str, str, str | None, int]:
    """``(product key, through, after, page size)`` of a valid request, else the fixed refusal."""
    products = normalize_products(product)
    through = normalize_version(to_version)
    after = normalize_version(from_version)
    if len(products) != 1 or through is None:
        raise InvalidEvidenceRequestError()
    product_key = products[0]
    if after is not None and is_empty_range(after, through):
        raise InvalidEvidenceRequestError()
    if max_facts not in (MAX_FACTS, MAX_IMPACT_FACTS):
        raise InvalidEvidenceRequestError()
    bounded = DEFAULT_FACTS if limit is None else limit
    if type(bounded) is not int or not 1 <= bounded <= max_facts:
        raise InvalidEvidenceRequestError()
    if query is not None and (type(query) is not str or not 0 < len(query.strip()) <= 500):
        raise InvalidEvidenceRequestError()
    if runtime.embedding is None:
        raise EvidenceGraphNotConfiguredError()
    return product_key, through, after, bounded


async def _episode_rows(db: AsyncSession, project_id: str, revision_ids: list[str]):
    return (
        await db.execute(
            select(
                KnowledgeGraphEpisode.episode_uuid,
                KnowledgeGraphEpisode.revision_id,
                KnowledgeGraphEpisode.span_ordinal,
            ).where(
                KnowledgeGraphEpisode.project_id == project_id,
                KnowledgeGraphEpisode.revision_id.in_(revision_ids),
            )
        )
    ).all()


async def _admit_query(db: AsyncSession, runtime: EvidenceRuntime, authorized: AuthorizedWorkspace) -> None:
    # A topic is embedded for the semantic edge search: the query text leaves the process, so the
    # reading Workspace is admitted first, like every other remote call.
    try:
        await admit_space(db, project_id=authorized.admission_project_id, space=runtime.embedding.space)
    except EmbeddingError as error:
        raise (
            EmbeddingSpaceDeniedError()
            if error.state is EmbeddingState.DENIED
            else EvidenceStoreNotConfiguredError()
        ) from None


async def _read_rows(
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    product_key: str,
    episode_span: dict[str, tuple[str, int]],
    query: object,
    kinds: frozenset[str] | None,
    max_facts: int,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The range's fact rows by uuid and their order (ranked by the topic when there is one)."""
    driver = PostgresGraphDriver(authorized.workspace.canonical)
    try:
        # A page without a topic is chosen from the whole range, so its totals are the range's.
        read_bound = max_facts if query is not None else MAX_IMPACT_FACTS
        if kinds is None:
            records, _, _ = await driver.execute_query(
                _FACTS, group=product_key, episodes=list(episode_span), limit=read_bound
            )
        else:
            records, _, _ = await driver.execute_query(
                _FACTS_OF_KINDS, group=product_key, episodes=list(episode_span), kinds=sorted(kinds), limit=read_bound
            )
        rows = {record["uuid"]: dict(record) for record in records}
        order = list(rows)
        if query is not None:
            ranked = await ranked_edge_uuids(driver, runtime, query.strip(), product_key, MAX_FACTS)
            order = [uuid for uuid in ranked if uuid in rows]
    finally:
        await driver.close()
    return rows, order


async def _whole_range_page(db, authorized, product_key: str, order, rows, episode_span, version_of):
    """``(facts in page order, kind counts)`` of a page without a topic."""
    # Without a topic, one page must show the breadth of a release, not its longest table: every fact
    # is cited, the kind counts cover all of them, and the page takes turns across the sections.
    facts = distinct(await _cited(db, authorized, order, rows, episode_span, version_of))
    counts = Counter(item.relation for item in facts)
    tiers: dict[int, list[ChangeFact]] = {}
    for item in facts:
        tiers.setdefault(_KIND_TIER.get(item.relation, len(_TIERS)), []).append(item)
    # Document structure decides what a page shows first (``change_ranking.py``).
    roles = await source_roles(db, authorized.project_id, (item.citation.source_id for item in facts))
    level = is_product_level(product_key)
    paged = [fact for tier in sorted(tiers) for fact in rank_tier(tiers[tier], roles, _kind_rank, level)]
    return paged, counts


__all__ = [
    "knowledge_changes",
]
