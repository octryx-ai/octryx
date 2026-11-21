"""Fuzzy duplicate candidates recorded as ``needs_review`` merge proposals."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeGraphNode, KnowledgeMergeProposal
from ....time_utils import utc_now
from ...knowledge_embedding.scoring import compute_semantic_similarity
from ..store import normalize_alias

# The package name keeps the log records under the identity logger.
logger = logging.getLogger(__package__)

_NAME_SIGNAL = "display_name"
_EMBEDDING_SIGNAL = "embedding"
_EMBEDDING_THRESHOLD = 0.92


def _name_key(node: KnowledgeGraphNode) -> str:
    return normalize_alias(node.display_name)


class _Proposer:
    """Records proposals once per unordered pair, skipping pairs that already have one."""

    def __init__(self, db: AsyncSession, project_id: str | None, existing_pairs: set[tuple[str, str]]) -> None:
        self.db = db
        self.project_id = project_id
        self.existing_pairs = existing_pairs
        self.proposals: list[KnowledgeMergeProposal] = []

    def propose(
        self, keep: KnowledgeGraphNode, merge: KnowledgeGraphNode, signal: str, confidence: float, reason: str
    ) -> None:
        if (keep.id, merge.id) in self.existing_pairs or keep.id == merge.id:
            return
        proposal = KnowledgeMergeProposal(
            id=str(uuid.uuid4()),
            project_id=self.project_id,
            keep_node_id=keep.id,
            merge_node_id=merge.id,
            signal=signal,
            confidence=confidence,
            reason=reason,
        )
        self.db.add(proposal)
        self.existing_pairs.add((keep.id, merge.id))
        self.existing_pairs.add((merge.id, keep.id))
        self.proposals.append(proposal)


def _propose_by_name(proposer: _Proposer, nodes: list[KnowledgeGraphNode], limit: int) -> None:
    """Signal 1: identical normalized display name within the same node_type."""
    by_name: dict[tuple[str, str], list[KnowledgeGraphNode]] = {}
    for node in nodes:
        key = (node.node_type, _name_key(node))
        if key[1]:
            by_name.setdefault(key, []).append(node)
    for (node_type, name), group in by_name.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda n: (n.created_at or utc_now(), n.id))
        keep = group[0]
        for merge in group[1:]:
            proposer.propose(
                keep,
                merge,
                _NAME_SIGNAL,
                0.7,
                f"Two {node_type} nodes share the display name '{name}'.",
            )
            if len(proposer.proposals) >= limit:
                return


def _propose_by_embedding(proposer: _Proposer, nodes: list[KnowledgeGraphNode], limit: int) -> None:
    """Signal 2: near-identical description embeddings within the same node_type."""
    embedded = [n for n in nodes if isinstance(n.embedding, list) and n.embedding]
    by_type: dict[str, list[KnowledgeGraphNode]] = {}
    for node in embedded:
        by_type.setdefault(node.node_type, []).append(node)
    for node_type, group in by_type.items():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if _name_key(a) == _name_key(b):
                    continue  # already covered by signal 1
                score = compute_semantic_similarity(a.embedding, b.embedding)
                if score >= _EMBEDDING_THRESHOLD:
                    keep, merge = sorted((a, b), key=lambda n: (n.created_at or utc_now(), n.id))
                    proposer.propose(
                        keep,
                        merge,
                        _EMBEDDING_SIGNAL,
                        round(score, 4),
                        f"Two {node_type} nodes have near-identical descriptions "
                        f"(similarity {score:.3f}): '{a.display_name}' vs '{b.display_name}'.",
                    )
                if len(proposer.proposals) >= limit:
                    return


async def propose_identity_merges(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    node_types: list[str] | None = None,
    limit: int = 50,
) -> list[KnowledgeMergeProposal]:
    """Scan for fuzzy duplicate candidates and record needs_review proposals.

    Candidates: two distinct active nodes of the same type whose normalized
    display names are identical (strong-ish but not deterministic — e.g. two
    'John Smith' person nodes may be different people), or whose description
    embeddings are near-identical. Existing proposals (any status) suppress
    re-proposing the same pair.
    """
    stmt = select(KnowledgeGraphNode).where(KnowledgeGraphNode.status == "active")
    if project_id is not None:
        stmt = stmt.where(
            or_(KnowledgeGraphNode.project_id == project_id, KnowledgeGraphNode.project_id.is_(None))
        )
    if node_types:
        stmt = stmt.where(KnowledgeGraphNode.node_type.in_([str(t).strip().lower() for t in node_types]))
    nodes = (await db.execute(stmt)).scalars().all()

    existing_pairs: set[tuple[str, str]] = set()
    for row in (await db.execute(select(KnowledgeMergeProposal))).scalars().all():
        existing_pairs.add((row.keep_node_id, row.merge_node_id))
        existing_pairs.add((row.merge_node_id, row.keep_node_id))

    proposer = _Proposer(db, project_id, existing_pairs)
    _propose_by_name(proposer, nodes, limit)
    if len(proposer.proposals) < limit:
        _propose_by_embedding(proposer, nodes, limit)

    await db.flush()
    return proposer.proposals
