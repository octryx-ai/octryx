"""``similar_to`` edges between sections of different manuals, from the stored span vectors.

No model is called: each section's first span already has its vector in the Workspace's Evidence
index (written by the projection's embedding step). For every section (bounded by the
profile) the build reads that vector with a registered fixed statement, asks the same space's
vector index for neighbours, maps each neighbour span to the section that contains it, and keeps the
best ``top_k`` sections of **other** manuals at or above ``min_score``. Only public spans take part
(the build has no reader), so a restricted manual never contributes a neighbour. An edge is cited
from both spans and, like every edge, served only when both resolve for the reader.

The pass is resumable: one call handles at most :data:`MAX_SECTIONS_PER_STEP` sections and stops
at the build slice's ``deadline`` (after at least one section, so every slice makes progress),
merging the edges it found (``store.merge_linkage``) and returning ``partial`` with a ``cursor``;
the next slice continues from there with the same ``pass_started``. The last step prunes the
``similar_to`` edges the pass did not state.

States: ``ok``, ``partial`` (continued by the next slice), ``needs_configuration`` (no embedding
space, or the Workspace has no vectors in it) and ``unavailable`` (the vector store failed); the
last two leave the remaining edges untouched.
"""

from __future__ import annotations

import bisect
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from ....models.project.knowledge_structured import KnowledgeStructuredExtraction, KnowledgeStructuredNode
from ....time_utils import utc_now
from ..access.acl_keys import PUBLIC_ACL_KEY
from ..evidence_index.errors import EvidenceIndexError
from ..evidence_index.operations import SEARCH_EVIDENCE_VECTOR, read_vector_operation
from ..ingestion.spans import derive_evidence_key
from ..projection.vector_spaces import vector_space_ready
from .profile_types import LAYER_MANUAL
from .store import merge_linkage, prune_linkage
from .store_types import LinkEdge

SECTION_TYPES = ("Chapter", "Section", "Subsection")
NEIGHBOUR_FETCH = 64
EDGE_SIMILAR = "similar_to"
MAX_SECTIONS_PER_STEP = 400
STATE_PARTIAL = "partial"


async def _sections(context, revisions: list[str]) -> list[tuple[str, str, int]]:
    rows = await context.db.execute(
        select(
            KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.revision_id, KnowledgeStructuredNode.span_ordinal
        )
        .where(
            KnowledgeStructuredNode.project_id == context.project_id,
            KnowledgeStructuredNode.revision_id.in_(revisions),
            KnowledgeStructuredNode.node_type.in_(SECTION_TYPES),
            KnowledgeStructuredNode.span_ordinal.is_not(None),
        )
        .order_by(KnowledgeStructuredNode.revision_id, KnowledgeStructuredNode.span_ordinal)
    )
    return [(str(row[0]), str(row[1]), int(row[2])) for row in rows.all()]


async def _manual_revisions(context, profile) -> list[str]:
    return sorted(
        str(row[0])
        for row in (
            await context.db.execute(
                select(KnowledgeStructuredExtraction.revision_id).where(
                    KnowledgeStructuredExtraction.project_id == context.project_id,
                    KnowledgeStructuredExtraction.layer == LAYER_MANUAL,
                    KnowledgeStructuredExtraction.profile == profile.profile_id,
                )
            )
        ).all()
    )


def _section_locator(sections: list[tuple[str, str, int]]):
    """Maps a span (revision, ordinal) to the section that contains it."""
    starts: dict[str, list[tuple[int, str]]] = {}
    for node, revision, ordinal in sections:
        starts.setdefault(revision, []).append((ordinal, node))

    def section_at(revision: str, ordinal: int) -> str | None:
        items = starts.get(revision) or []
        index = bisect.bisect_right(items, (ordinal, "￿")) - 1
        return items[index][1] if index >= 0 else None

    return section_at


def _rank_neighbours(neighbours, *, revision: str, by_hex: dict, section_at, profile) -> list:
    """The best ``top_k`` sections of other manuals among a section's neighbour spans."""
    found: dict[str, tuple[float, str, int]] = {}
    for hit in neighbours:
        hex_form, _, raw_ordinal = str(hit.get("evidence_key") or "").partition(":")
        other = by_hex.get(hex_form)
        if other is None or other == revision or not raw_ordinal.isdigit():
            continue
        distance = hit.get("distance")
        if type(distance) not in (int, float):
            continue
        score = round(1.0 - float(distance), 4)
        target = section_at(other, int(raw_ordinal))
        if target is None or score < profile.similarity_min_score:
            continue
        if target not in found or score > found[target][0]:
            found[target] = (score, other, int(raw_ordinal))
    return sorted(found.items(), key=lambda item: (-item[1][0], item[0]))[: profile.similarity_top_k]


async def _neighbours(context, space, revision: str, ordinal: int) -> list | None:
    """The neighbour spans of a section's first span; ``None`` when that span has no vector."""
    runtime = context.runtime
    key = derive_evidence_key(revision, ordinal)
    rows = await runtime.runtime_client.run(
        context.workspace, read_vector_operation(space.key), {"evidence_key": key}
    )
    vector = rows[0].get("vector") if rows else None
    if not vector:
        return None
    return await runtime.runtime_client.run(
        context.workspace,
        SEARCH_EVIDENCE_VECTOR,
        {
            "space": space.key, "vector": vector, "principals": [PUBLIC_ACL_KEY], "k": NEIGHBOUR_FETCH,
        },
    )


def _keep_best(best: dict, ranked: list, node: str, revision: str, ordinal: int) -> None:
    for target, (score, other, other_ordinal) in ranked:
        pair = tuple(sorted((node, target)))
        if pair in best and best[pair].properties["score"] >= score:
            continue
        citations = sorted([(revision, ordinal, None), (other, other_ordinal, None)])
        best[pair] = LinkEdge(EDGE_SIMILAR, pair[0], pair[1], citations, {"score": score})


async def link_similar_sections(context, *, deadline: float | None = None, progress: dict | None = None) -> dict:
    """One step of the similarity pass; ``progress`` is the previous step's ``partial`` result."""
    embedding = getattr(context.runtime, "embedding", None)
    if embedding is None or not await vector_space_ready(context.db, context.project_id, embedding.space.key):
        return {"state": "needs_configuration"}
    profile = context.profile
    revisions = await _manual_revisions(context, profile)
    sections = (await _sections(context, revisions))[: profile.similarity_max_sections] if len(revisions) > 1 else []
    by_hex = {uuid.UUID(revision).hex: revision for revision in revisions}
    section_at = _section_locator(sections)
    resume = progress if isinstance(progress, dict) and progress.get("state") == STATE_PARTIAL else {}
    cursor = min(int(resume.get("cursor") or 0), len(sections))
    pass_started = datetime.fromisoformat(resume["pass_started"]) if resume.get("pass_started") else utc_now()
    best: dict[tuple[str, str], LinkEdge] = {}
    position = cursor
    try:
        for node, revision, ordinal in sections[cursor : cursor + MAX_SECTIONS_PER_STEP]:
            if deadline is not None and position > cursor and time.monotonic() > deadline:
                break
            position += 1
            neighbours = await _neighbours(context, embedding.space, revision, ordinal)
            if neighbours is None:
                continue
            ranked = _rank_neighbours(neighbours, revision=revision, by_hex=by_hex, section_at=section_at,
                                      profile=profile)
            _keep_best(best, ranked, node, revision, ordinal)
    except EvidenceIndexError:
        return {"state": "unavailable"}
    counts = await merge_linkage(
        context.db, project_id=context.project_id, layer=LAYER_MANUAL, profile_id=profile.profile_id,
        desired=list(best.values()), pass_started=pass_started,
    )
    added = int(resume.get("added") or 0) + counts.edges
    if position < len(sections):
        return {"state": STATE_PARTIAL, "cursor": position, "pass_started": pass_started.isoformat(),
                "sections": len(sections), "added": added}
    removed, kept = await prune_linkage(
        context.db, project_id=context.project_id, layer=LAYER_MANUAL, edge_type=EDGE_SIMILAR,
        profile_id=profile.profile_id, pass_started=pass_started,
    )
    return {"state": "ok", "sections": len(sections), "edges": kept, "added": added, "removed": removed}


__all__ = ["EDGE_SIMILAR", "MAX_SECTIONS_PER_STEP", "STATE_PARTIAL", "link_similar_sections"]
