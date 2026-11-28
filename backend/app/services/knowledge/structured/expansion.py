"""Structured one-hop facts behind search hits."""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.temporal.changes_facts import ChangeFact

from ....models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from ..access.authorization import AuthorizedWorkspace
from ..ingestion.spans import derive_evidence_key
from ..ledger.citations import resolve_citations
from ..temporal.fact_expansion import VIA_HIT, VIA_HOP, ExpandedFact
from .describe import describe
from .read import cites_of, visible_nodes, visible_revisions
from .workspace_profile import workspace_profile_id

MAX_SEED_NODES = 40
MAX_CANDIDATE_EDGES = 400
# Structural edges (a file defines its keys, a chapter contains its sections) say little a hit does not
# already show; findings and typed relations come first.
_STRUCTURAL = frozenset({"defines", "contains", "documented_in", "changes_file", "references", "row_of", "similar_to"})


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.casefold()) if len(term) > 2}


async def _seeds(db: AsyncSession, project_id: str, hits: list[tuple[str, int]], query: str) -> list[str]:
    by_revision: dict[str, list[int]] = {}
    for revision, ordinal in hits:
        by_revision.setdefault(revision, []).append(ordinal)
    rows = (await db.execute(
        select(
            KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.revision_id, KnowledgeStructuredNode.span_ordinal,
            KnowledgeStructuredNode.label,
        )
        .where(
            KnowledgeStructuredNode.project_id == project_id,
            KnowledgeStructuredNode.profile == await workspace_profile_id(db, project_id),
            or_(*(
                (KnowledgeStructuredNode.revision_id == revision) & KnowledgeStructuredNode.span_ordinal.in_(ordinals)
                for revision, ordinals in by_revision.items()
            )),
        )
        .limit(MAX_SEED_NODES * 4)
    )).all()
    rank = {span: index for index, span in enumerate(hits)}
    wanted = _terms(query)

    def order(row) -> tuple:
        # A node the query names (``RequestTimeout``) before the other keys of the same chunk.
        overlap = len(wanted & _terms(str(row[3])))
        return (-overlap, rank.get((str(row[1]), int(row[2])), len(rank)), str(row[0]))

    seeds: list[str] = []
    for node_id, _, _, _ in sorted(rows, key=order):
        if node_id not in seeds:
            seeds.append(str(node_id))
    return seeds[:MAX_SEED_NODES]


async def structured_hit_facts(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    hits: list[tuple[str, int]],
    products: tuple[str, ...] | None,
    version: str | None = None,
    query: str = "",
    limit: int,
) -> tuple[ExpandedFact, ...]:
    if not hits:
        return ()
    seeds = await _seeds(db, authorized.project_id, hits, query)
    if not seeds:
        return ()
    edges = (await db.execute(
        select(KnowledgeStructuredEdge)
        .where(
            KnowledgeStructuredEdge.project_id == authorized.project_id,
            KnowledgeStructuredEdge.profile == await workspace_profile_id(db, authorized.project_id),
            or_(KnowledgeStructuredEdge.source_id.in_(seeds), KnowledgeStructuredEdge.target_id.in_(seeds)),
        )
        .order_by(KnowledgeStructuredEdge.edge_key)
        .limit(MAX_CANDIDATE_EDGES)
    )).scalars().all()
    visible = await visible_revisions(db, authorized, {cite[0] for edge in edges for cite in cites_of(edge.citations)})
    edges = [edge for edge in edges if all(cite[0] in visible for cite in cites_of(edge.citations))]
    nodes = await visible_nodes(db, authorized, {e.source_id for e in edges} | {e.target_id for e in edges})
    hit_spans = set(hits)
    seed_rank = {node_id: index for index, node_id in enumerate(seeds)}

    def order(edge) -> tuple:
        direct = any((cite[0], cite[1]) in hit_spans for cite in cites_of(edge.citations))
        touching = min(seed_rank.get(edge.source_id, len(seeds)), seed_rank.get(edge.target_id, len(seeds)))
        return (edge.edge_type in _STRUCTURAL, touching, 0 if direct else 1, edge.edge_type, edge.edge_key)

    chosen = [edge for edge in sorted(edges, key=order) if edge.source_id in nodes and edge.target_id in nodes]
    first_cites = {edge.id: next(
        (cite for cite in cites_of(edge.citations) if (cite[0], cite[1]) in hit_spans), cites_of(edge.citations)[0]
    ) for edge in chosen}
    keys = {edge_id: derive_evidence_key(cite[0], cite[1]) for edge_id, cite in first_cites.items()}
    resolved = await resolve_citations(
        db, authorized.project_id, tuple(sorted(set(keys.values()))), principal_keys=authorized.principal_keys
    )
    return _facts(chosen, nodes, first_cites, keys, resolved, hit_spans, products, version, limit)


def _facts(chosen, nodes, first_cites, keys, resolved, hit_spans, products, version, limit) -> tuple[ExpandedFact, ...]:
    facts: list[ExpandedFact] = []
    for edge in chosen:
        citation = resolved.get(keys[edge.id])
        if citation is None or (products and not set(citation.products) & set(products)):
            continue
        if version is not None and citation.version != version:
            continue
        source, target = nodes[edge.source_id], nodes[edge.target_id]
        fact = ChangeFact(
            relation=edge.edge_type.upper(), fact=describe(edge.edge_type, source.label, target.label, edge.properties),
            source_entity=source.label, target_entity=target.label, version=citation.version, citation=citation,
            supporting_episodes=0,
        )
        direct = (first_cites[edge.id][0], first_cites[edge.id][1]) in hit_spans
        facts.append(ExpandedFact(fact, VIA_HIT if direct else VIA_HOP))
        if len(facts) >= limit:
            break
    return tuple(facts)


__all__ = ["structured_hit_facts"]
