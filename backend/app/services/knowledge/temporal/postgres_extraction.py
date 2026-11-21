"""Relationship extraction into the PostgreSQL graph (graph on Postgres, part B write side).

A governed model reads a small batch of a revision's spans at once and answers with typed facts,
each naming the passage it was read from; the facts are written into ``kg_node``/``kg_edge`` and
every span of the batch gets its episode row (``knowledge_graph_episodes``), which is what
citations, the changes page and the extraction gap read. The extraction profile is data
(``profiles/*.json``): its closed relation
types, their descriptions and its instructions are the prompt, and the change-record self-check
demotes a fact whose own check says it states no change.

Entities are resolved inside the Workspace's product group: the same name (case and spacing
folded) is the same entity, and a new name whose embedding is nearly identical to an existing
entity's name (cosine >= ``SAME_ENTITY_SIMILARITY``) is that entity too. A fact already in the graph
with the same endpoints, relation and text gains the new episode instead of becoming a duplicate.

Everything is written through the caller's session and committed by the caller, so a batch is
recorded completely or not at all. Rerunning a span replaces its episode and converges.
"""


from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_temporal import KnowledgeGraphEpisode
from ..embedding.port import EmbeddingPurpose, EmbeddingRuntime
from .errors import GraphStoreError, GraphStoreState
from .extraction_profiles import ExtractionProfile
from .postgres_extraction_graph import _Graph, ensure_workspace_graph, vectors_available
from .postgres_extraction_model import (
    _SPACE,
    ANSWER_ATTEMPTS,
    MAX_ANSWER_TOKENS,
    MAX_FACT_CHARS,
    MAX_FACTS_PER_CALL,
    MAX_NAME_CHARS,
    BatchResult,
    ExtractionAnswer,
    SpanInput,
    _Message,
    _relation,
    build_messages,
    episode_uuid,
    normalized_name,
)

logger = logging.getLogger(__name__)

_Fact = tuple[int, str, str, str, str]


async def extract_batch(
    db: AsyncSession,
    *,
    llm: Any,
    embedding: EmbeddingRuntime,
    profile: ExtractionProfile,
    project_id: str,
    revision_id: str,
    group: str,
    version: str | None,
    title: str,
    valid_at: datetime,
    spans: list[SpanInput],
) -> BatchResult:
    """Extract one batch of a revision's spans and record an episode for each of them (caller commits)."""
    result = BatchResult(spans=len(spans))
    if not spans:
        return result
    await ensure_workspace_graph(db, project_id, embedding.space.key)
    messages = build_messages(profile, title=title, group=group, version=version, spans=spans)
    answer = await _answer(llm, messages)
    facts = _valid_facts(answer, profile, spans, result)
    result.facts = len(facts)

    # Each span's episode is replaced, whichever profile wrote it before: one episode per span.
    episodes = {span.ordinal: episode_uuid(project_id, revision_id, span.ordinal, profile.profile_id) for span in spans}
    await _drop_old_episodes(db, project_id, revision_id, episodes)

    graph = _Graph(db, project_id, group, embedding, await vectors_available(db))
    counts = await _write_facts(graph, embedding, facts, spans, episodes, valid_at, result)
    for span in spans:
        db.add(
            KnowledgeGraphEpisode(
                episode_uuid=episodes[span.ordinal],
                project_id=project_id,
                revision_id=revision_id,
                span_ordinal=span.ordinal,
                group_id=group[:60],
                extraction_profile=profile.profile_id,
                node_count=0,
                edge_count=counts.get(span.ordinal, 0),
            )
        )
    await db.flush()
    return result


async def _answer(llm: Any, messages: list[_Message]) -> dict[str, Any]:
    answer: dict[str, Any] = {}
    for attempt in range(ANSWER_ATTEMPTS):
        try:
            answer = await llm._generate_response(
                messages, response_model=ExtractionAnswer, max_tokens=MAX_ANSWER_TOKENS
            )
            break
        except json.JSONDecodeError:
            if attempt == ANSWER_ATTEMPTS - 1:
                raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION) from None
    return answer


def _valid_facts(
    answer: dict[str, Any], profile: ExtractionProfile, spans: list[SpanInput], result: BatchResult
) -> list[_Fact]:
    facts: list[_Fact] = []
    for item in (answer.get("facts") or [])[:MAX_FACTS_PER_CALL]:
        source, target = str(item.get("source") or "").strip(), str(item.get("target") or "").strip()
        fact = _SPACE.sub(" ", str(item.get("fact") or "")).strip()[:MAX_FACT_CHARS]
        passage = item.get("passage")
        relation = _relation(str(item.get("relation") or ""), profile, bool(item.get("states_version_change")), result)
        valid = (
            type(passage) is int
            and 1 <= passage <= len(spans)
            and relation
            and fact
            and 0 < len(source) <= MAX_NAME_CHARS
            and 0 < len(target) <= MAX_NAME_CHARS
            and normalized_name(source) != normalized_name(target)
        )
        if not valid:
            result.dropped += 1
            continue
        facts.append((passage, source, relation, target, fact))
    return facts


async def _drop_old_episodes(db: AsyncSession, project_id: str, revision_id: str, episodes: dict[int, str]) -> None:
    old = (
        (
            await db.execute(
                select(KnowledgeGraphEpisode.episode_uuid).where(
                    KnowledgeGraphEpisode.revision_id == revision_id,
                    KnowledgeGraphEpisode.span_ordinal.in_(list(episodes)),
                )
            )
        )
        .scalars()
        .all()
    )
    for previous in old:
        await db.execute(
            text(
                "UPDATE kg_edge SET episodes = array_remove(episodes, :e) WHERE project_id = :p AND :e = ANY(episodes)"
            ),
            {"e": previous, "p": project_id},
        )
    await db.execute(
        delete(KnowledgeGraphEpisode).where(
            KnowledgeGraphEpisode.revision_id == revision_id,
            KnowledgeGraphEpisode.span_ordinal.in_(list(episodes)),
        )
    )


async def _write_facts(
    graph: _Graph,
    embedding: EmbeddingRuntime,
    facts: list[_Fact],
    spans: list[SpanInput],
    episodes: dict[int, str],
    valid_at: datetime,
    result: BatchResult,
) -> dict[int, int]:
    """Write the facts; ``span ordinal -> facts written from it``."""
    resolved = await graph.entities([name for _, source, _, target, _ in facts for name in (source, target)], result)
    vectors = await embedding.embedder.embed([fact for *_, fact in facts], EmbeddingPurpose.DOCUMENT) if facts else []
    counts: dict[int, int] = {}
    for (passage, source, relation, target, fact), vector in zip(facts, vectors, strict=True):
        ordinal = spans[passage - 1].ordinal
        await graph.fact(
            resolved[normalized_name(source)],
            relation,
            resolved[normalized_name(target)],
            fact,
            episodes[ordinal],
            valid_at,
            vector,
            result,
        )
        counts[ordinal] = counts.get(ordinal, 0) + 1
    return counts


__all__ = [
    "extract_batch",
]
