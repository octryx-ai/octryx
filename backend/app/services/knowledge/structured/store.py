"""Writing the structured graph: per-revision replace, retirement, and linkage diffs."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import (
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from ....time_utils import utc_now
from .build_states import BuildLease
from .facts import Extraction
from .store_revisions import _delete_revision_rows, _keep_written, _rows, hold_lease
from .store_types import LinkEdge, WriteCounts

# The batch size and ``time`` stay module globals here: the writers below read them through this
# module, so tests can shrink a batch or stop the slice clock on ``store``.
INSERT_BATCH = 500


async def _insert(db: AsyncSession, model, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), INSERT_BATCH):
        await db.execute(insert(model), rows[start : start + INSERT_BATCH])


async def write_revision(
    db: AsyncSession,
    *,
    project_id: str,
    revision_id: str,
    layer: str,
    profile_id: str,
    extractor: str,
    extraction: Extraction,
    resume: bool = False,
    deadline: float | None = None,
    lease: BuildLease | None = None,
) -> tuple[WriteCounts, bool]:
    # At least one batch per call, so a revision larger than one slice still completes.
    if lease is not None:
        await hold_lease(db, lease)
    await db.execute(
        delete(KnowledgeStructuredExtraction).where(
            KnowledgeStructuredExtraction.project_id == project_id,
            KnowledgeStructuredExtraction.revision_id == revision_id,
        )
    )
    nodes, edges = _rows(project_id, revision_id, layer, profile_id, extraction)
    if resume:
        new_nodes, new_edges, removed_nodes, removed_edges = await _keep_written(
            db, project_id, revision_id, profile_id, nodes, edges
        )
    else:
        removed_nodes, removed_edges = await _delete_revision_rows(db, project_id, [revision_id])
        new_nodes, new_edges = nodes, edges
    batches = [(KnowledgeStructuredNode, new_nodes[start : start + INSERT_BATCH])
               for start in range(0, len(new_nodes), INSERT_BATCH)]
    batches += [(KnowledgeStructuredEdge, new_edges[start : start + INSERT_BATCH])
                for start in range(0, len(new_edges), INSERT_BATCH)]
    inserted = {KnowledgeStructuredNode: 0, KnowledgeStructuredEdge: 0}
    for index, (model, batch) in enumerate(batches):
        if index and deadline is not None and time.monotonic() > deadline:
            counts = WriteCounts(inserted[KnowledgeStructuredNode], inserted[KnowledgeStructuredEdge],
                                 removed_nodes, removed_edges)
            return counts, False
        await db.execute(insert(model), batch)
        inserted[model] += len(batch)
    db.add(
        KnowledgeStructuredExtraction(
            revision_id=revision_id, profile=profile_id, project_id=project_id, layer=layer, extractor=extractor,
            node_count=len(nodes), edge_count=len(edges), warnings=dict(sorted(extraction.warnings.items())),
            extracted_at=utc_now(),
        )
    )
    counts = WriteCounts(inserted[KnowledgeStructuredNode], inserted[KnowledgeStructuredEdge], removed_nodes,
                         removed_edges)
    return counts, True


async def replace_revision(
    db: AsyncSession,
    *,
    project_id: str,
    revision_id: str,
    layer: str,
    profile_id: str,
    extractor: str,
    extraction: Extraction,
) -> WriteCounts:
    counts, _ = await write_revision(
        db, project_id=project_id, revision_id=revision_id, layer=layer, profile_id=profile_id, extractor=extractor,
        extraction=extraction,
    )
    return counts


async def sync_linkage(
    db: AsyncSession, *, project_id: str, layer: str, profile_id: str, desired: list[LinkEdge]
) -> WriteCounts:
    wanted = {edge.key: edge for edge in desired}
    rows = (
        await db.execute(
            select(KnowledgeStructuredEdge).where(
                KnowledgeStructuredEdge.project_id == project_id,
                KnowledgeStructuredEdge.revision_id.is_(None),
                KnowledgeStructuredEdge.layer == layer,
            )
        )
    ).scalars().all()
    removed, kept = 0, set()
    for row in rows:
        edge = wanted.get(row.edge_key)
        if edge is None or row.profile != profile_id:
            await db.delete(row)
            removed += 1
            continue
        kept.add(row.edge_key)
        citations = [list(item) for item in edge.citations]
        if row.properties != edge.properties or row.citations != citations:
            row.properties, row.citations = edge.properties, citations
    now = utc_now()
    new = [
        {
            "id": str(uuid.uuid4()), "project_id": project_id, "revision_id": None, "profile": profile_id,
            "layer": layer, "edge_type": edge.edge_type, "edge_key": key, "source_id": edge.source_id,
            "target_id": edge.target_id, "properties": edge.properties,
            "citations": [list(item) for item in edge.citations], "created_at": now,
        }
        for key, edge in wanted.items()
        if key not in kept
    ]
    await db.flush()
    await _insert(db, KnowledgeStructuredEdge, new)
    return WriteCounts(edges=len(new), removed_edges=removed)


def _score(properties: object) -> float:
    value = (properties or {}).get("score") if isinstance(properties, dict) else None
    return float(value) if type(value) in (int, float) else float("-inf")


async def merge_linkage(
    db: AsyncSession, *, project_id: str, layer: str, profile_id: str, desired: list[LinkEdge], pass_started: datetime
) -> WriteCounts:
    wanted = {edge.key: edge for edge in desired}
    if not wanted:
        return WriteCounts()
    rows = {
        row.edge_key: row
        for row in (
            await db.execute(
                select(KnowledgeStructuredEdge).where(
                    KnowledgeStructuredEdge.project_id == project_id,
                    KnowledgeStructuredEdge.edge_key.in_(sorted(wanted)),
                )
            )
        ).scalars().all()
    }
    now = utc_now()
    new = []
    for key, edge in wanted.items():
        row = rows.get(key)
        if row is None:
            new.append({
                "id": str(uuid.uuid4()), "project_id": project_id, "revision_id": None, "profile": profile_id,
                "layer": layer, "edge_type": edge.edge_type, "edge_key": key, "source_id": edge.source_id,
                "target_id": edge.target_id, "properties": edge.properties,
                "citations": [list(item) for item in edge.citations], "created_at": now,
            })
            continue
        current = row.profile == profile_id and row.created_at is not None and row.created_at >= pass_started
        if current and _score(row.properties) >= _score(edge.properties):
            continue
        row.profile, row.layer, row.created_at = profile_id, layer, now
        row.properties, row.citations = edge.properties, [list(item) for item in edge.citations]
    await db.flush()
    await _insert(db, KnowledgeStructuredEdge, new)
    return WriteCounts(edges=len(new))


async def prune_linkage(
    db: AsyncSession, *, project_id: str, layer: str, edge_type: str, profile_id: str, pass_started: datetime
) -> tuple[int, int]:
    scope = (
        KnowledgeStructuredEdge.project_id == project_id,
        KnowledgeStructuredEdge.revision_id.is_(None),
        KnowledgeStructuredEdge.layer == layer,
        KnowledgeStructuredEdge.edge_type == edge_type,
    )
    removed = await db.execute(
        delete(KnowledgeStructuredEdge).where(
            *scope,
            or_(KnowledgeStructuredEdge.profile != profile_id, KnowledgeStructuredEdge.created_at < pass_started),
        )
    )
    kept = (await db.execute(select(func.count()).select_from(KnowledgeStructuredEdge).where(*scope))).scalar_one()
    return int(removed.rowcount or 0), int(kept)


__all__ = [
    "merge_linkage",
    "prune_linkage",
    "replace_revision",
    "sync_linkage",
    "write_revision",
]
