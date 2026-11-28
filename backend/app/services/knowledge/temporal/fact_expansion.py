"""The graph facts behind one Workspace's search hits, plus one hop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_temporal import KnowledgeGraphEpisode, KnowledgeGraphWorkspace
from ..access.authorization import AuthorizedWorkspace
from ..embedding.port import EmbeddingError, EmbeddingState
from ..embedding.selection import admit_space
from ..runtime import EvidenceRuntime
from .change_ranking import distinct
from .changes_facts import ChangeFact, cited_facts, ranked_edge_uuids
from .errors import GraphStoreError
from .postgres_graph import PostgresGraphDriver

MAX_SEED_EPISODES = 40
MAX_DIRECT_FACTS = 60
MAX_HOP_ENTITIES = 40
MAX_HOP_FACTS = 120
EDGE_SEARCH_LIMIT = 50
MAX_EDGE_QUERY_CHARS = 500
RRF_K = 60

STATE_OK = "ok"
STATE_NOT_EXTRACTED = "not_extracted"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_DENIED = "denied"
STATE_UNAVAILABLE = "unavailable"
STATE_TIMEOUT = "timeout"
STATE_CONTRACT_VIOLATION = "contract_violation"
VIA_HIT = "hit"
VIA_HOP = "related"

_RETURN = (
    "RETURN e.uuid AS uuid, e.name AS relation, e.fact AS fact, e.episodes AS episodes, "
    "e.created_at AS created_at, a.name AS source, b.name AS target, a.uuid AS source_uuid, "
    "b.uuid AS target_uuid ORDER BY e.uuid LIMIT $limit"
)
_DIRECT = (
    "MATCH (a:Entity)-[e:RELATES_TO]->(b:Entity) "
    "WHERE e.group_id = $group AND size([episode IN e.episodes WHERE episode IN $episodes]) > 0 " + _RETURN
)
_HOP = (
    "MATCH (a:Entity)-[e:RELATES_TO]->(b:Entity) "
    "WHERE e.group_id = $group AND (a.uuid IN $entities OR b.uuid IN $entities) " + _RETURN
)


@dataclass(frozen=True, slots=True)
class ExpandedFact:
    fact: ChangeFact
    # ``hit``: extracted from a hit span; ``related``: one hop away and ranked by the query.
    via: str


@dataclass(frozen=True, slots=True)
class WorkspaceFacts:
    state: str
    facts: tuple[ExpandedFact, ...] = ()
    seed_episodes: int = 0


@dataclass(frozen=True, slots=True)
class _Seed:
    episode_span: dict[str, tuple[str, int]]
    # Group -> its seed episodes in hit order.
    groups: dict[str, list[str]]
    hit_rank: dict[str, int]


async def _seeds(
    db: AsyncSession, project_id: str, hits: list[tuple[str, int]], products: tuple[str, ...] | None
) -> _Seed:
    rows = (
        await db.execute(
            select(
                KnowledgeGraphEpisode.episode_uuid,
                KnowledgeGraphEpisode.revision_id,
                KnowledgeGraphEpisode.span_ordinal,
                KnowledgeGraphEpisode.group_id,
            ).where(
                KnowledgeGraphEpisode.project_id == project_id,
                KnowledgeGraphEpisode.revision_id.in_(sorted({revision for revision, _ in hits})),
            )
        )
    ).all()
    by_span = {(str(row[1]), int(row[2])): (str(row[0]), str(row[3])) for row in rows}
    seed = _Seed({}, {}, {})
    for rank, span in enumerate(hits, start=1):
        found = by_span.get(span)
        if found is None or found[0] in seed.episode_span or len(seed.episode_span) >= MAX_SEED_EPISODES:
            continue
        episode, group = found
        if products and group not in products:
            continue
        seed.episode_span[episode] = span
        seed.groups.setdefault(group, []).append(episode)
        seed.hit_rank[episode] = rank
    return seed


async def _episode_spans(db: AsyncSession, project_id: str, episodes: set[str]) -> dict[str, tuple[str, int]]:
    if not episodes:
        return {}
    rows = await db.execute(
        select(
            KnowledgeGraphEpisode.episode_uuid, KnowledgeGraphEpisode.revision_id, KnowledgeGraphEpisode.span_ordinal
        ).where(
            KnowledgeGraphEpisode.project_id == project_id,
            KnowledgeGraphEpisode.episode_uuid.in_(sorted(episodes)),
        )
    )
    return {str(row[0]): (str(row[1]), int(row[2])) for row in rows.all()}


async def _read_group(driver, runtime: EvidenceRuntime, query: str, group: str, episodes: list[str]):
    records, _, _ = await driver.execute_query(_DIRECT, group=group, episodes=episodes, limit=MAX_DIRECT_FACTS)
    direct = {record["uuid"]: dict(record) for record in records}
    entities: list[str] = []
    for row in direct.values():
        for entity in (row.get("source_uuid"), row.get("target_uuid")):
            if entity and entity not in entities and len(entities) < MAX_HOP_ENTITIES:
                entities.append(entity)
    hop: dict[str, dict[str, Any]] = {}
    if entities:
        records, _, _ = await driver.execute_query(_HOP, group=group, entities=entities, limit=MAX_HOP_FACTS)
        hop = {record["uuid"]: dict(record) for record in records if record["uuid"] not in direct}
    ranking = await ranked_edge_uuids(driver, runtime, query, group, EDGE_SEARCH_LIMIT)
    return direct, hop, ranking


def _fused_order(direct: dict[str, dict], hop: dict[str, dict], ranking: list[str], hit_rank: dict[str, int]):
    def first_hit(row: dict) -> int:
        return min((hit_rank[episode] for episode in row.get("episodes") or () if episode in hit_rank), default=0)

    by_hit = sorted(direct, key=lambda uuid: (first_hit(direct[uuid]), str(direct[uuid].get("created_at") or ""), uuid))
    scores: dict[str, float] = {}
    for rank, uuid in enumerate([uuid for uuid in ranking if uuid in direct or uuid in hop], start=1):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, uuid in enumerate(by_hit, start=1):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda uuid: (-scores[uuid], uuid))


def _in_bounds(fact: ChangeFact, products: tuple[str, ...] | None, version: str | None) -> bool:
    if products and not set(fact.citation.products) & set(products):
        return False
    return version is None or fact.citation.version == version


async def expand_workspace_facts(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    query: str,
    hits: list[tuple[str, int]],
    products: tuple[str, ...] | None,
    version: str | None,
    deadline: float,
    limit: int,
) -> WorkspaceFacts:
    if runtime.embedding is None:
        return WorkspaceFacts(STATE_NEEDS_CONFIGURATION)
    graph = await db.get(KnowledgeGraphWorkspace, authorized.project_id)
    if graph is None:
        return WorkspaceFacts(STATE_NOT_EXTRACTED)
    if graph.embedding_space_key != runtime.embedding.space.key:
        # The graph's vectors belong to another space; ranking them with this one would be wrong.
        return WorkspaceFacts(STATE_CONTRACT_VIOLATION)
    seed = await _seeds(db, authorized.project_id, hits, products)
    if not seed.episode_span:
        return WorkspaceFacts(STATE_NOT_EXTRACTED)
    try:
        # The query is embedded for the edge search: admitted for the reading Workspace first.
        await admit_space(db, project_id=authorized.admission_project_id, space=runtime.embedding.space)
    except EmbeddingError as error:
        return WorkspaceFacts(STATE_DENIED if error.state is EmbeddingState.DENIED else STATE_NEEDS_CONFIGURATION)

    read: list[tuple[dict, dict, list[str]]] = []
    driver = PostgresGraphDriver(authorized.workspace.canonical)
    try:
        async with asyncio.timeout_at(deadline):
            for group, episodes in seed.groups.items():
                read.append(await _read_group(driver, runtime, query[:MAX_EDGE_QUERY_CHARS], group, episodes))
    except TimeoutError:
        return WorkspaceFacts(STATE_TIMEOUT, seed_episodes=len(seed.episode_span))
    except GraphStoreError as error:
        return WorkspaceFacts(error.state.value, seed_episodes=len(seed.episode_span))
    except EmbeddingError as error:
        return WorkspaceFacts(error.state.value, seed_episodes=len(seed.episode_span))
    finally:
        await driver.close()

    rows, ordered = _interleaved(read, seed.hit_rank)
    kept = await _cited_in_bounds(db, authorized, rows, ordered, seed.episode_span, products, version)
    unique = {id(fact) for fact in distinct(item.fact for item in kept)}
    facts = tuple(item for item in kept if id(item.fact) in unique)[:limit]
    return WorkspaceFacts(STATE_OK, facts, len(seed.episode_span))


def _interleaved(read: list[tuple[dict, dict, list[str]]], hit_rank: dict[str, int]):
    rows: dict[str, dict[str, Any]] = {}
    queues: list[list[tuple[str, str]]] = []
    for direct, hop, ranking in read:
        rows.update(direct)
        rows.update(hop)
        fused = _fused_order(direct, hop, ranking, hit_rank)
        queues.append([(uuid, VIA_HIT if uuid in direct else VIA_HOP) for uuid in fused])
    # Groups (products) take turns, in the order their first hit appeared.
    ordered: list[tuple[str, str]] = []
    while queues:
        ordered.extend(queue.pop(0) for queue in queues)
        queues = [queue for queue in queues if queue]
    return rows, ordered


async def _cited_in_bounds(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    rows: dict[str, dict[str, Any]],
    ordered: list[tuple[str, str]],
    episode_span: dict[str, tuple[str, int]],
    products: tuple[str, ...] | None,
    version: str | None,
) -> list[ExpandedFact]:
    direct_uuids = [uuid for uuid, via in ordered if via == VIA_HIT]
    hop_uuids = [uuid for uuid, via in ordered if via == VIA_HOP]
    hop_spans = await _episode_spans(
        db, authorized.project_id, {episode for uuid in hop_uuids for episode in rows[uuid].get("episodes") or ()}
    )
    # A direct fact is cited from its hit span, a hop fact from its own first span; the version is
    # the citation's own.
    cited = dict(await cited_facts(db, authorized, direct_uuids, rows, episode_span, {}))
    cited.update(await cited_facts(db, authorized, hop_uuids, rows, hop_spans, {}))
    return [
        ExpandedFact(cited[uuid], via)
        for uuid, via in ordered
        if uuid in cited and _in_bounds(cited[uuid], products, version)
    ]


__all__ = [
    "MAX_DIRECT_FACTS",
    "MAX_HOP_FACTS",
    "VIA_HIT",
    "VIA_HOP",
    "ExpandedFact",
    "WorkspaceFacts",
    "expand_workspace_facts",
]
