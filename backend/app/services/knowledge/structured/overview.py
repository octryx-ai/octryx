"""The structured explorer's overview sample and totals.

Without them the overview shows only the structural spine (``runs_in``, ``configures``) and says nothing
about how big the graph is. Two cheap reads fix that:

- :func:`domain_seeds` — the best-connected nodes of **every** node type (top ``per_type`` by degree),
  so rules, merchants, teams, models … appear next to the spine. One grouped query, bounded.
- :func:`structured_totals` — distinct nodes and edges this reader may see: rows of visible revisions;
  a cross-revision edge (no own revision, e.g. ``inconsistent_across``) counts when both endpoints are
  visible. Cached for a minute per Workspace, reader principals and layers.
"""

from __future__ import annotations

import time

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from ..access.authorization import AuthorizedWorkspace
from .read import CHUNK, visible_revisions
from .workspace_profile import workspace_profile_id

PER_TYPE = 5
MAX_TYPES = 40
TOTALS_SECONDS = 60
_cache: dict[tuple, tuple[float, dict]] = {}


async def domain_seeds(
    db: AsyncSession, project_id: str, profile_id: str, layers: tuple[str, ...], per_type: int = PER_TYPE
) -> dict[str, list[str]]:
    """``{node_type: [node ids by degree desc]}``, at most ``per_type`` per type and :data:`MAX_TYPES` types."""
    edge, node = KnowledgeStructuredEdge, KnowledgeStructuredNode
    scope = (edge.project_id == project_id, edge.profile == profile_id, edge.layer.in_(layers))
    ends = union_all(
        select(edge.source_id.label("nid")).where(*scope), select(edge.target_id.label("nid")).where(*scope)
    ).subquery()
    degree = select(ends.c.nid, func.count().label("degree")).group_by(ends.c.nid).subquery()
    typed = (
        select(node.node_id, node.node_type).where(node.project_id == project_id, node.profile == profile_id)
        .distinct().subquery()
    )
    ranked = select(
        typed.c.node_id, typed.c.node_type, degree.c.degree,
        func.row_number().over(partition_by=typed.c.node_type,
                               order_by=(degree.c.degree.desc(), typed.c.node_id)).label("rank"),
    ).join(degree, degree.c.nid == typed.c.node_id).subquery()
    rows = (await db.execute(
        select(ranked.c.node_type, ranked.c.node_id).where(ranked.c.rank <= per_type)
        .order_by(ranked.c.node_type, ranked.c.rank)
    )).all()
    seeds: dict[str, list[str]] = {}
    for node_type, node_id in rows:
        if node_type in seeds or len(seeds) < MAX_TYPES:
            seeds.setdefault(str(node_type), []).append(str(node_id))
    return seeds


async def structured_totals(db: AsyncSession, authorized: AuthorizedWorkspace, layers: tuple[str, ...]) -> dict:
    """``{nodes, edges}`` of the structured layers this reader may see."""
    key = (authorized.project_id, tuple(sorted(authorized.principal_keys or ())), layers)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TOTALS_SECONDS:
        return hit[1]
    project_id = authorized.project_id
    profile_id = await workspace_profile_id(db, project_id)
    node, edge = KnowledgeStructuredNode, KnowledgeStructuredEdge
    node_scope = (node.project_id == project_id, node.profile == profile_id, node.layer.in_(layers))
    revisions = {str(row[0]) for row in (await db.execute(select(node.revision_id).where(*node_scope).distinct()))}
    edge_scope = (edge.project_id == project_id, edge.profile == profile_id, edge.layer.in_(layers))
    revisions |= {str(row[0]) for row in (await db.execute(
        select(edge.revision_id).where(*edge_scope, edge.revision_id.is_not(None)).distinct()))}
    visible = sorted(await visible_revisions(db, authorized, revisions))
    nodes = edges = 0
    if visible:
        # Distinct node ids over chunks: collect ids (one column) rather than double-count across chunks.
        node_ids: set[str] = set()
        for start in range(0, len(visible), CHUNK):
            chunk = visible[start : start + CHUNK]
            node_ids.update(str(row[0]) for row in await db.execute(
                select(node.node_id).where(*node_scope, node.revision_id.in_(chunk)).distinct()))
            edges += int((await db.execute(select(func.count()).select_from(edge).where(
                *edge_scope, edge.revision_id.in_(chunk)))).scalar() or 0)
        nodes = len(node_ids)
        orphan_edges = (await db.execute(
            select(edge.source_id, edge.target_id).where(*edge_scope, edge.revision_id.is_(None)))).all()
        edges += sum(1 for source, target in orphan_edges if source in node_ids and target in node_ids)
    totals = {"nodes": nodes, "edges": edges}
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = (time.monotonic(), totals)
    return totals


__all__ = ["PER_TYPE", "domain_seeds", "structured_totals"]
