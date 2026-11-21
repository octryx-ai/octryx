"""The structured layers in the Workspace graph explorer: a bounded, cited window.

Three ways in, all bounded (:data:`MAX_CANDIDATES` edges read, ``max_nodes`` shown):

- **Overview** (no query, no focus): each requested layer's spine — manual documents and their
  chapters plus compatibility edges, configuration files to components plus inconsistencies,
  deployments/namespaces/clusters plus incident causes and assignment groups — with the layers
  taking turns, so a small view still shows each of them — and, taking turns with them, the
  best-connected nodes of every node type (``overview.domain_seeds``), so rules, merchants, teams,
  models … show up and not only ``runs_in``/``configures``.
- **Query**: nodes whose label contains the query (case-insensitive), with their edges.
- **Focus**: one node's edges.

Every edge is served only when every revision it cites is visible to the reader, with its
citations resolved (page, section, file line); a node only when the reader can see a statement of
it. Node descriptions use typed properties only; a redacted value stays ``[redacted]``.
"""

from __future__ import annotations

from itertools import zip_longest
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from ..access.authorization import AuthorizedWorkspace
from .describe import describe
from .overview import PER_TYPE, domain_seeds
from .profile_types import LAYERS
from .read import cites_of, presented_citations, visible_nodes, visible_revisions
from .workspace_profile import workspace_profile_id

MAX_CANDIDATES = 600
MAX_EDGES = 300
MAX_SEEDS = 50
_OVERVIEW = {
    "manual": ("contains", "requires", "supports"),
    "configuration": ("configures", "inconsistent_across"),
    "operations": ("runs_in", "caused_by", "assigned_to_group", "uses_image", "affects_service"),
}
_SPINE_SOURCES = {"contains": ("Document",), "configures": ("ConfigFile",)}
_PROVENANCE = ("citation", "cite_as", "evidence_key", "source_title", "source_url", "section", "source_id",
               "revision_id", "page", "line")


def node_summary(node_type: str, props: dict[str, Any]) -> str:
    if node_type == "Parameter":
        parts = [f"default {props['default']}" if props.get("default") is not None else "",
                 props.get("unit") or "", props.get("description") or ""]
        return " ".join(part for part in parts if part)[:300]
    if node_type == "ConfiguredSetting":
        return f"{props.get('path')} line {props.get('line')}: {props.get('value')}"
    if node_type in ("Incident", "Change", "Problem", "JiraIssue"):
        return " · ".join(str(props[key]) for key in ("title", "state", "status", "opened_at", "created_at")
                          if props.get(key))[:300]
    return str(props.get("title") or props.get("number") or "")[:300]


async def _edges(db: AsyncSession, statement, limit: int = MAX_CANDIDATES) -> list:
    return list((await db.execute(statement.order_by(KnowledgeStructuredEdge.edge_key).limit(limit))).scalars().all())


def _touching(node_ids):
    return or_(KnowledgeStructuredEdge.source_id.in_(node_ids), KnowledgeStructuredEdge.target_id.in_(node_ids))


async def _candidates(db: AsyncSession, project_id: str, layers: tuple[str, ...], query: str, focus: str):
    profile_id = await workspace_profile_id(db, project_id)
    edge, node = KnowledgeStructuredEdge, KnowledgeStructuredNode
    base = select(edge).where(edge.project_id == project_id, edge.profile == profile_id, edge.layer.in_(layers))
    if focus:
        return await _edges(db, base.where(_touching([focus]))), set()
    if query:
        matching = (
            select(node.node_id)
            .where(node.project_id == project_id, node.profile == profile_id, node.layer.in_(layers),
                   func.lower(node.label).contains(query, autoescape=True))
            .distinct().order_by(node.node_id).limit(MAX_SEEDS)
        )
        seeds = [str(row[0]) for row in (await db.execute(matching)).all()]
        return (await _edges(db, base.where(_touching(seeds))), set(seeds)) if seeds else ([], set())
    per_layer: list[list] = []
    for layer in layers:
        found: list = []
        per_layer.append(found)
        for edge_type in _OVERVIEW.get(layer, ()):
            statement = base.where(edge.layer == layer, edge.edge_type == edge_type)
            if edge_type in _SPINE_SOURCES:
                spine = select(node.node_id).where(
                    node.project_id == project_id, node.node_type.in_(_SPINE_SOURCES[edge_type])
                )
                statement = statement.where(edge.source_id.in_(spine))
            found.extend(await _edges(db, statement, limit=100))
    # Each node type's best-connected nodes, a few edges each, after the spines in every round.
    for seeds in (await domain_seeds(db, project_id, profile_id, layers)).values():
        per_layer.append(await _edges(db, base.where(_touching(seeds)), limit=PER_TYPE * 4))
    # Layers take turns, so a bounded overview shows every requested layer, not the first one only.
    interleaved = [edge for group in zip_longest(*per_layer) for edge in group if edge is not None]
    return list({edge.id: edge for edge in interleaved}.values()), set()


async def structured_explorer(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, query: str, focus_node_id: str, max_nodes: int,
    layers: tuple[str, ...] = LAYERS,
) -> dict[str, Any]:
    """``{state, nodes, edges, truncated}`` of the structured layers for this reader."""
    layers = tuple(layer for layer in layers if layer in LAYERS)
    if not layers:
        return {"state": "not_requested", "nodes": [], "edges": [], "truncated": False}
    query = query.strip().casefold()[:500]
    edges, seeds = await _candidates(db, authorized.project_id, layers, query, focus_node_id)
    truncated = len(edges) >= MAX_CANDIDATES
    visible = await visible_revisions(db, authorized, {cite[0] for edge in edges for cite in cites_of(edge.citations)})
    edges = [edge for edge in edges if all(cite[0] in visible for cite in cites_of(edge.citations))]
    nodes = await visible_nodes(db, authorized, {e.source_id for e in edges} | {e.target_id for e in edges})
    shown: dict[str, dict[str, Any]] = {}
    kept = []
    for edge in edges:
        if edge.source_id not in nodes or edge.target_id not in nodes:
            continue
        new = {edge.source_id, edge.target_id} - shown.keys()
        if len(shown) + len(new) > max_nodes or len(kept) >= MAX_EDGES:
            truncated = True
            continue
        for node_id in (edge.source_id, edge.target_id):
            if node_id not in shown:
                view = nodes[node_id]
                matched = bool(query and query in view.label.casefold()) or node_id in seeds
                shown[node_id] = {
                    "id": node_id, "node_type": view.node_type, "display_name": view.label,
                    "description": node_summary(view.node_type, view.properties), "degree": 0,
                    "trust_level": "deterministic", "matched": matched, "layer": view.layer,
                }
            shown[node_id]["degree"] += 1
        kept.append(edge)
    citations = await presented_citations(db, authorized, [cite for edge in kept for cite in cites_of(edge.citations)])
    presented = []
    for edge in kept:
        cited = [citations[cite] for cite in cites_of(edge.citations) if cite in citations]
        primary = cited[0] if cited else {}
        presented.append({
            "id": edge.id, "source": edge.source_id, "target": edge.target_id, "edge_type": edge.edge_type,
            "description": describe(edge.edge_type, nodes[edge.source_id].label, nodes[edge.target_id].label,
                                    edge.properties),
            "layer": edge.layer, **{key: primary.get(key) for key in _PROVENANCE}, "citations": cited,
        })
    state = "ok" if shown else "no_matches" if query or focus_node_id else "not_built"
    return {"state": state, "nodes": list(shown.values()), "edges": presented, "truncated": truncated}


async def structured_node_detail(db: AsyncSession, *, authorized: AuthorizedWorkspace, node_id: str) -> dict | None:
    graph = await structured_explorer(db, authorized=authorized, query="", focus_node_id=node_id, max_nodes=150)
    nodes = {node["id"]: node for node in graph["nodes"]}
    if node_id not in nodes:
        views = await visible_nodes(db, authorized, {node_id})
        if node_id not in views:
            return None
        view = views[node_id]
        nodes[node_id] = {"id": node_id, "node_type": view.node_type, "display_name": view.label,
                          "description": node_summary(view.node_type, view.properties), "degree": 0,
                          "trust_level": "deterministic", "matched": False, "layer": view.layer}
    view = (await visible_nodes(db, authorized, {node_id}))[node_id]
    relations, claims = [], []
    for edge in graph["edges"]:
        provenance = {key: edge.get(key) for key in _PROVENANCE}
        outgoing = edge["source"] == node_id
        peer = nodes[edge["target"] if outgoing else edge["source"]]
        relations.append({"edge_type": edge["edge_type"], "direction": "out" if outgoing else "in",
                          "peer_id": peer["id"], "peer_name": peer["display_name"], "peer_type": peer["node_type"],
                          "description": edge["description"], "citations": edge["citations"], **provenance})
        claims.append({"claim_type": edge["edge_type"], "statement": edge["description"],
                       "valid_from_label": None, "valid_until_label": None, **provenance})
    own = await presented_citations(db, authorized, [view.cite] if view.cite else [])
    properties = {key: value for key, value in view.properties.items() if key != "stub" and value not in (None, "", [])}
    return {
        **nodes[node_id], "workspace_id": authorized.project_id, "state": "ok", "truncated": graph["truncated"],
        "status": "deterministic", "properties": properties, "aliases": [],
        "citation": own.get(view.cite) if view.cite else None,
        "source_refs": sorted({edge["cite_as"] for edge in graph["edges"] if edge.get("cite_as")}),
        "claims": claims, "relations": relations,
    }


__all__ = ["node_summary", "structured_explorer", "structured_node_detail"]
