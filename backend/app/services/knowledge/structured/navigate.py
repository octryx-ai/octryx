"""Bounded, cited navigation of the structured graph for tools: neighbours and operations chains.

- :func:`graph_neighbors` resolves an entity name to nodes by exact label forms only (``RequestTimeout``
  matches ``[Cache?] RequestTimeout``, ``HttpService.RequestTimeout`` and a setting ``[S] RequestTimeout``;
  ``INC0000105`` matches the record ``INC0000105 …``) and returns their one-hop facts.
- :func:`ops_chain` follows one ticket (incident, change, problem, Jira issue) or one service: its
  record, causes, mentions in both directions (which Jira issues hang on a change), the
  configuration settings whose comments mention it, and — for an incident — the changes opened
  before it that affected the same service, else the same assignment group (the ``basis`` says
  which; no service field means no service claim).

Every fact is served only when every revision it rests on is visible to the reader, with its
resolved citations; results are data (``content_is_data``), never instructions.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from ..access.authorization import AuthorizedWorkspace
from .describe import describe
from .explorer import node_summary
from .read import cites_of, presented_citations, visible_nodes, visible_revisions
from .workspace_profile import workspace_profile_id

MAX_ENTITY_NODES = 20
MAX_FACTS = 60
MAX_PRIOR = 10
MAX_ENTITY_CHARS = 200
TICKET_TYPES = ("Incident", "Change", "Problem", "JiraIssue")


async def _nodes_named(db: AsyncSession, project_id: str, entity: str, node_types=None) -> list[str]:
    label = KnowledgeStructuredNode.label
    forms = or_(
        label == entity,
        label.startswith(f"{entity} ", autoescape=True),
        label.endswith(f"] {entity}", autoescape=True),
        label.endswith(f".{entity}", autoescape=True),
    )
    statement = select(KnowledgeStructuredNode.node_id).where(
        KnowledgeStructuredNode.project_id == project_id,
        KnowledgeStructuredNode.profile == await workspace_profile_id(db, project_id),
        forms,
    )
    if node_types:
        statement = statement.where(KnowledgeStructuredNode.node_type.in_(node_types))
    rows = await db.execute(statement.distinct().order_by(KnowledgeStructuredNode.node_id).limit(MAX_ENTITY_NODES))
    return [str(row[0]) for row in rows.all()]


async def _edges_of(db: AsyncSession, project_id: str, node_ids: list[str], edge_types=None, limit=MAX_FACTS * 4):
    statement = select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.project_id == project_id,
        KnowledgeStructuredEdge.profile == await workspace_profile_id(db, project_id),
        or_(KnowledgeStructuredEdge.source_id.in_(node_ids), KnowledgeStructuredEdge.target_id.in_(node_ids)),
    )
    if edge_types:
        statement = statement.where(KnowledgeStructuredEdge.edge_type.in_(edge_types))
    return list((await db.execute(statement.order_by(KnowledgeStructuredEdge.edge_key).limit(limit))).scalars().all())


class _Served:
    """Visible edges and nodes of one read, presented with resolved citations."""

    def __init__(self, db: AsyncSession, authorized: AuthorizedWorkspace) -> None:
        self.db, self.authorized = db, authorized
        self.nodes: dict = {}

    async def visible(self, edges: list) -> list:
        revisions = {cite[0] for edge in edges for cite in cites_of(edge.citations)}
        visible = await visible_revisions(self.db, self.authorized, revisions)
        edges = [edge for edge in edges if all(cite[0] in visible for cite in cites_of(edge.citations))]
        wanted = ({e.source_id for e in edges} | {e.target_id for e in edges}) - self.nodes.keys()
        self.nodes.update(await visible_nodes(self.db, self.authorized, wanted))
        return [edge for edge in edges if edge.source_id in self.nodes and edge.target_id in self.nodes]

    async def node_entries(self, node_ids: list[str]) -> list[dict[str, Any]]:
        self.nodes.update(await visible_nodes(self.db, self.authorized, set(node_ids) - self.nodes.keys()))
        views = [self.nodes[node_id] for node_id in node_ids if node_id in self.nodes]
        cites = await presented_citations(self.db, self.authorized, [view.cite for view in views if view.cite])
        return [{"id": view.node_id, "type": view.node_type, "label": view.label, "layer": view.layer,
                 "summary": node_summary(view.node_type, view.properties),
                 "citation": cites.get(view.cite) if view.cite else None} for view in views]

    async def facts(self, edges: list) -> list[dict[str, Any]]:
        cites = await presented_citations(self.db, self.authorized, [c for e in edges for c in cites_of(e.citations)])
        return [{
            "relation": edge.edge_type, "layer": edge.layer,
            "statement": describe(edge.edge_type, self.nodes[edge.source_id].label, self.nodes[edge.target_id].label,
                                  edge.properties),
            "source": self.nodes[edge.source_id].label, "target": self.nodes[edge.target_id].label,
            "citations": [cites[c] for c in cites_of(edge.citations) if c in cites],
        } for edge in edges]


def _bounded(value: object) -> str | None:
    text = str(value or "").strip()[:MAX_ENTITY_CHARS]
    return text or None


async def graph_neighbors(db: AsyncSession, *, authorized: AuthorizedWorkspace, entity: object) -> dict[str, Any]:
    name = _bounded(entity)
    result: dict[str, Any] = {"entity": name, "state": "ok", "content_is_data": True, "nodes": [], "facts": [],
                              "truncated": False}
    if name is None:
        return {**result, "state": "invalid_request"}
    node_ids = await _nodes_named(db, authorized.project_id, name)
    served = _Served(db, authorized)
    result["nodes"] = await served.node_entries(node_ids)
    if not result["nodes"]:
        return {**result, "state": "not_found"}
    edges = await served.visible(await _edges_of(db, authorized.project_id, [n["id"] for n in result["nodes"]]))
    result["truncated"] = len(edges) > MAX_FACTS
    result["facts"] = await served.facts(edges[:MAX_FACTS])
    return result


def _opened(view) -> str:
    return str(view.properties.get("opened_at") or view.properties.get("created_at") or "")


async def _prior_changes(db, served: _Served, project_id: str, record, edges) -> dict[str, Any] | None:
    if record.node_type != "Incident" or not _opened(record):
        return None
    for edge_type, basis in (("affects_service", "same_service"), ("assigned_to_group", "same_assignment_group")):
        anchors = [e.target_id for e in edges if e.source_id == record.node_id and e.edge_type == edge_type]
        if not anchors:
            continue
        linked = await served.visible(await _edges_of(db, project_id, anchors, (edge_type,), limit=2000))
        changes = sorted(
            {e.source_id for e in linked if served.nodes[e.source_id].node_type == "Change"
             and _opened(served.nodes[e.source_id]) and _opened(served.nodes[e.source_id]) < _opened(record)},
            key=lambda node_id: _opened(served.nodes[node_id]), reverse=True,
        )
        return {"basis": basis, "anchor": [served.nodes[a].label for a in anchors if a in served.nodes],
                "changes": await served.node_entries(changes[:MAX_PRIOR]), "total": len(changes)}
    return {"basis": "none", "anchor": [], "changes": [], "total": 0}


async def ops_chain(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, ticket: object = None, service: object = None
) -> dict[str, Any]:
    ticket, service = _bounded(ticket), _bounded(service)
    result: dict[str, Any] = {"ticket": ticket, "service": service, "state": "ok", "content_is_data": True,
                              "records": [], "facts": [], "configuration": [], "prior_changes": None}
    if (ticket is None) == (service is None):
        return {**result, "state": "invalid_request"}
    served = _Served(db, authorized)
    if service is not None:
        anchors = await _nodes_named(db, authorized.project_id, service, ("Service", "ConfigurationItem"))
        edges = await served.visible(await _edges_of(db, authorized.project_id, anchors,
                                                     ("affects_service", "affects_ci"), limit=2000))
        records = sorted({e.source_id for e in edges}, key=lambda n: _opened(served.nodes[n]), reverse=True)
        result["records"] = await served.node_entries(records[:MAX_FACTS])
        result["facts"] = await served.facts([e for e in edges if e.source_id in set(records[:MAX_FACTS])])
        return result if result["records"] else {**result, "state": "not_found"}
    found = await _nodes_named(db, authorized.project_id, ticket, TICKET_TYPES)
    result["records"] = await served.node_entries(found)
    if not result["records"]:
        return {**result, "state": "not_found"}
    edges = await served.visible(await _edges_of(db, authorized.project_id, found))
    config = [e for e in edges if served.nodes[e.source_id].node_type in ("ConfiguredSetting", "ConfigFile")]
    other = [e for e in edges if e not in config]
    result["facts"] = await served.facts(other[:MAX_FACTS])
    result["configuration"] = await served.facts(config[:MAX_FACTS])
    record = served.nodes.get(found[0])
    if record is not None:
        result["prior_changes"] = await _prior_changes(db, served, authorized.project_id, record, edges)
    return result


__all__ = ["graph_neighbors", "ops_chain"]
