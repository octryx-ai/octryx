"""Per-revision row work behind the structured-graph writer in :mod:`.store`."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import (
    KnowledgeStructuredBuild,
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from ....time_utils import utc_now
from .build_states import STATE_RUNNING, BuildLease, BuildLeaseLostError
from .facts import Extraction
from .store_types import WriteCounts


def _edge_key(revision_id: str, edge_type: str, source_id: str, target_id: str) -> str:
    return hashlib.sha256(f"{revision_id}|{edge_type}|{source_id}|{target_id}".encode()).hexdigest()


async def _delete_revision_rows(db: AsyncSession, project_id: str, revision_ids: list[str]) -> tuple[int, int]:
    edges = await db.execute(
        delete(KnowledgeStructuredEdge).where(
            KnowledgeStructuredEdge.project_id == project_id, KnowledgeStructuredEdge.revision_id.in_(revision_ids)
        )
    )
    nodes = await db.execute(
        delete(KnowledgeStructuredNode).where(
            KnowledgeStructuredNode.project_id == project_id, KnowledgeStructuredNode.revision_id.in_(revision_ids)
        )
    )
    await db.execute(
        delete(KnowledgeStructuredExtraction).where(
            KnowledgeStructuredExtraction.project_id == project_id,
            KnowledgeStructuredExtraction.revision_id.in_(revision_ids),
        )
    )
    return int(nodes.rowcount or 0), int(edges.rowcount or 0)


def _rows(project_id: str, revision_id: str, layer: str, profile_id: str, extraction: Extraction):
    now = utc_now()
    nodes = [
        {
            "id": str(uuid.uuid4()), "project_id": project_id, "revision_id": revision_id, "profile": profile_id,
            "layer": layer, "node_type": ref.node_type, "node_key": ref.node_key, "node_id": ref.id,
            "label": node.label, "properties": node.properties,
            "span_ordinal": node.cite.span_ordinal if node.cite else None,
            "line": node.cite.line if node.cite else None, "created_at": now,
        }
        for ref, node in extraction.nodes.items()
    ]
    edges = [
        {
            "id": str(uuid.uuid4()), "project_id": project_id, "revision_id": revision_id, "profile": profile_id,
            "layer": layer, "edge_type": edge.edge_type,
            "edge_key": _edge_key(revision_id, edge.edge_type, edge.source.id, edge.target.id),
            "source_id": edge.source.id, "target_id": edge.target.id, "properties": edge.properties,
            "citations": [[revision_id, cite.span_ordinal, cite.line] for cite in edge.cites], "created_at": now,
        }
        for edge in extraction.edges.values()
    ]
    return nodes, edges


async def _keep_written(
    db: AsyncSession, project_id: str, revision_id: str, profile_id: str, nodes: list[dict], edges: list[dict]
) -> tuple[list[dict], list[dict], int, int]:
    node_model, edge_model = KnowledgeStructuredNode, KnowledgeStructuredEdge
    removed = []
    for model in (edge_model, node_model):
        result = await db.execute(delete(model).where(
            model.project_id == project_id, model.revision_id == revision_id, model.profile != profile_id
        ))
        removed.append(int(result.rowcount or 0))
    removed_edges, removed_nodes = removed
    written_nodes = {
        (row[1], row[2]): row[0] for row in (await db.execute(
            select(node_model.id, node_model.node_type, node_model.node_key)
            .where(node_model.revision_id == revision_id, node_model.profile == profile_id)
        )).all()
    }
    written_edges = {
        row[1]: row[0] for row in (await db.execute(
            select(edge_model.id, edge_model.edge_key)
            .where(edge_model.revision_id == revision_id, edge_model.profile == profile_id)
        )).all()
    }
    wanted_nodes = {(row["node_type"], row["node_key"]) for row in nodes}
    wanted_edges = {row["edge_key"] for row in edges}
    gone_nodes = [row_id for key, row_id in written_nodes.items() if key not in wanted_nodes]
    gone_edges = [row_id for key, row_id in written_edges.items() if key not in wanted_edges]
    if gone_edges:
        await db.execute(delete(edge_model).where(edge_model.id.in_(gone_edges)))
    if gone_nodes:
        await db.execute(delete(node_model).where(node_model.id.in_(gone_nodes)))
    missing_nodes = [row for row in nodes if (row["node_type"], row["node_key"]) not in written_nodes]
    missing_edges = [row for row in edges if row["edge_key"] not in written_edges]
    return missing_nodes, missing_edges, removed_nodes + len(gone_nodes), removed_edges + len(gone_edges)


async def hold_lease(db: AsyncSession, lease: BuildLease) -> None:
    # An expired lease nobody claimed is still this worker's.
    held = await db.execute(
        update(KnowledgeStructuredBuild)
        .where(
            KnowledgeStructuredBuild.id == lease.build_id,
            KnowledgeStructuredBuild.state == STATE_RUNNING,
            KnowledgeStructuredBuild.claimed_by == lease.worker_id[:120],
        )
        .values(lease_until=utc_now() + timedelta(seconds=lease.lease_seconds))
    )
    if held.rowcount != 1:
        raise BuildLeaseLostError()


async def partial_revisions(db: AsyncSession, *, project_id: str, layer: str, profile_id: str) -> set[str]:
    ledger = select(KnowledgeStructuredExtraction.revision_id).where(
        KnowledgeStructuredExtraction.project_id == project_id
    )
    found: set[str] = set()
    for model in (KnowledgeStructuredNode, KnowledgeStructuredEdge):
        rows = await db.execute(
            select(model.revision_id).distinct().where(
                model.project_id == project_id, model.layer == layer, model.profile == profile_id,
                model.revision_id.is_not(None), model.revision_id.not_in(ledger),
            )
        )
        found.update(str(row[0]) for row in rows.all())
    return found


async def retire_revisions(db: AsyncSession, *, project_id: str, revision_ids: list[str]) -> WriteCounts:
    if not revision_ids:
        return WriteCounts()
    removed_nodes, removed_edges = await _delete_revision_rows(db, project_id, revision_ids)
    return WriteCounts(removed_nodes=removed_nodes, removed_edges=removed_edges)


__all__ = ["hold_lease", "partial_revisions", "retire_revisions"]
