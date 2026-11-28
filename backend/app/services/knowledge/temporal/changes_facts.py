"""The cited fact rows behind ``knowledge_changes`` and the graph's ranked edge search (``changes``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..embedding.port import EmbeddingPurpose
from ..ingestion.spans import derive_evidence_key
from ..ledger.citations import ResolvedCitation, resolve_citations
from ..runtime import EvidenceRuntime

RRF_K = 60


@dataclass(frozen=True, slots=True)
class ChangeFact:
    relation: str
    fact: str
    source_entity: str
    target_entity: str
    version: str | None
    citation: ResolvedCitation
    supporting_episodes: int
    # When Graphiti created the edge: within one span, the model extracts facts in text order.
    extracted_at: str = ""


@dataclass(frozen=True, slots=True)
class ChangesResult:
    state: str
    product: str
    from_version: str | None
    to_version: str
    versions: tuple[str, ...]
    facts: tuple[ChangeFact, ...]
    episodes: int
    # How many cited facts of each kind the range has in total, beyond the returned page.
    kind_counts: dict[str, int] = field(default_factory=dict)


def _rrf(*rankings: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda key: -scores[key])


async def ranked_edge_uuids(driver, runtime: EvidenceRuntime, query: str, group: str, limit: int) -> list[str]:
    vector = (await runtime.embedding.embedder.embed([query], EmbeddingPurpose.QUERY))[0]
    return _rrf(*await driver.ranked_edges(query, group, vector, limit))


async def _cited(db, authorized, order, rows: dict[str, dict[str, Any]], episode_span, version_of) -> list[ChangeFact]:
    return [fact for _, fact in await cited_facts(db, authorized, order, rows, episode_span, version_of)]


async def cited_facts(
    db, authorized, order, rows: dict[str, dict[str, Any]], episode_span, version_of
) -> list[tuple[str, ChangeFact]]:
    first_span = {}
    for uuid in order:
        supporting = [episode_span[episode] for episode in rows[uuid]["episodes"] or () if episode in episode_span]
        if supporting:
            first_span[uuid] = (min(supporting, key=lambda span: span[1]), len(supporting))
    keys = {uuid: derive_evidence_key(span[0], span[1]) for uuid, (span, _) in first_span.items()}
    # A fact is shown only with a citation its reader may open: restricted sources stay restricted.
    citations = await resolve_citations(
        db, authorized.project_id, tuple(set(keys.values())), principal_keys=authorized.principal_keys
    )
    facts: list[tuple[str, ChangeFact]] = []
    for uuid in order:
        citation = citations.get(keys.get(uuid, ""))
        if citation is None:
            continue
        row = rows[uuid]
        facts.append((
            uuid,
            ChangeFact(
                relation=str(row.get("relation") or ""),
                fact=str(row.get("fact") or ""),
                source_entity=str(row.get("source") or ""),
                target_entity=str(row.get("target") or ""),
                version=version_of.get(citation.revision_id, citation.version),
                citation=citation,
                supporting_episodes=first_span[uuid][1],
                extracted_at=str(row.get("created_at") or ""),
            ),
        ))
    return facts
