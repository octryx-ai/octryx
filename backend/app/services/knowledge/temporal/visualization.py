"""Source-authorized, bounded visualization of the current facts of the Workspace graph. Every cited episode is resolved
against the ledger and source ACL."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import Counter

from ..retrieval.locator import citation_link
from .changes_facts import cited_facts
from .errors import GraphStoreError
from .postgres_graph import PostgresGraphDriver
from .visualization_queries import (
    COUNT_QUERY,
    FACTS_QUERY,
    MAX_CANDIDATES,
    MAX_EDGES,
    MAX_NODES,
    QUERY_SECONDS,
    visible_episodes,
)

TOTALS_SECONDS = 60
_totals_cache: dict[str, tuple[float, dict]] = {}


async def _totals(driver, workspace_id: str, episodes: list[str]) -> dict | None:
    key = hashlib.sha256("\0".join([workspace_id, *sorted(episodes)]).encode()).hexdigest()
    hit = _totals_cache.get(key)
    if hit and time.monotonic() - hit[0] < TOTALS_SECONDS:
        return hit[1]
    try:
        records, _, _ = await driver.execute_query(COUNT_QUERY, episodes=episodes)
    except GraphStoreError:
        return None  # the shown window stays valid; only N is unknown
    if not isinstance(records, list) or not records:
        return None
    row = dict(records[0])
    if not all(type(row.get(name)) is int for name in ("nodes", "edges")):
        return None
    totals = {"nodes": row["nodes"], "edges": row["edges"]}
    if len(_totals_cache) > 256:
        _totals_cache.clear()
    _totals_cache[key] = (time.monotonic(), totals)
    return totals


def _empty(workspace_id, state, *, query="", truncated=False):
    return {
        "store": "extracted_graph", "workspace_id": workspace_id, "state": state, "truncated": truncated,
        "nodes": [], "edges": [], "match_ids": [] if query else None,
        "stats": {
            "shown_nodes": 0, "shown_edges": 0, "matched_nodes": 0 if query else None,
            "match_limit": MAX_NODES, "scope": "project", "counts_scope": "visible",
            "total_nodes": None, "total_edges": None, "total_claims": None, "total_communities": None,
            "node_types": {}, "edge_types": {},
        },
    }


def _provenance(fact):
    citation = fact.citation
    return {
        "citation": citation.citation, "cite_as": citation_link(citation),
        "evidence_key": citation.evidence_key, "source_title": citation.source_title,
        "source_url": citation.source_url, "section": " > ".join(citation.section_path) or None,
        "source_id": citation.source_id, "revision_id": citation.revision_id,
    }


def _present(workspace_id, cited, rows, query, max_nodes, truncated):
    result = _empty(workspace_id, "ok", query=query, truncated=truncated)
    nodes = {}
    edges = []
    for uuid, fact in cited:
        row = rows[uuid]
        source, target = row["source_uuid"], row["target_uuid"]
        new_ids = {source, target} - nodes.keys()
        if len(nodes) + len(new_ids) > max_nodes or len(edges) >= MAX_EDGES:
            result["truncated"] = True
            continue
        # The fact text and names come only from an edge with readable evidence. Entity
        # summaries may incorporate other restricted sources and must never be exposed.
        fact_matches = bool(query and query in fact.fact.casefold())
        for node_id, name in ((source, fact.source_entity), (target, fact.target_entity)):
            matched = bool(query and (query in name.casefold() or fact_matches))
            node = nodes.setdefault(node_id, {
                "id": node_id, "node_type": "entity", "display_name": name,
                "description": "", "degree": 0, "trust_level": "extracted", "matched": False,
            })
            node["degree"] += 1
            node["matched"] = node["matched"] or matched
        edges.append({
            "id": uuid, "source": source, "target": target, "edge_type": fact.relation,
            "description": fact.fact, **_provenance(fact),
        })
    result["nodes"], result["edges"] = list(nodes.values()), edges
    result["match_ids"] = [node["id"] for node in nodes.values() if node["matched"]] if query else None
    result["stats"].update({
        "shown_nodes": len(nodes), "shown_edges": len(edges),
        "matched_nodes": len(result["match_ids"]) if query else None,
        "node_types": {"entity": len(nodes)} if nodes else {},
        "edge_types": dict(Counter(edge["edge_type"] for edge in edges)),
    })
    if not nodes:
        result["state"] = "no_matches"
    return result


async def build_current_graph(db, *, runtime, authorized, query="", focus_node_id="", max_nodes=150):
    query = query.strip().casefold()[:500]
    max_nodes = max(2, min(int(max_nodes), MAX_NODES))
    def empty(state):
        return _empty(authorized.project_id, state, query=query)

    episodes, truncated = await visible_episodes(db, authorized)
    if not episodes:
        return empty("not_extracted")
    episode_spans = {item.episode_uuid: (item.revision_id, item.span_ordinal) for item in episodes}
    try:
        driver = PostgresGraphDriver(authorized.workspace.canonical)
        try:
            async with asyncio.timeout(QUERY_SECONDS):
                records, _, _ = await driver.execute_query(
                    FACTS_QUERY, episodes=list(episode_spans), query=query,
                    focus=focus_node_id, limit=MAX_CANDIDATES + 1,
                )
                totals = await _totals(driver, authorized.project_id, list(episode_spans))
        finally:
            await asyncio.wait_for(driver.close(), timeout=2)
    except TimeoutError:
        return empty("timeout")
    except GraphStoreError as error:
        return empty(error.state.value)
    if not isinstance(records, list):
        return empty("contract_violation")
    truncated = truncated or len(records) > MAX_CANDIDATES
    rows = {}
    for record in records[:MAX_CANDIDATES]:
        row = dict(record)
        if not all(isinstance(row.get(key), str) and row[key] for key in ("uuid", "source_uuid", "target_uuid")):
            return empty("contract_violation")
        if not isinstance(row.get("episodes"), list) or not all(
            isinstance(episode, str) for episode in row["episodes"]
        ):
            return empty("contract_violation")
        # Recheck selectors on returned projection rows before provenance resolution.
        if focus_node_id and focus_node_id not in (row["source_uuid"], row["target_uuid"]):
            continue
        if query and not any(query in str(row.get(key) or "").casefold() for key in ("source", "target", "fact")):
            continue
        rows[row["uuid"]] = row
    cited = await cited_facts(db, authorized, list(rows), rows, episode_spans, {})
    result = _present(authorized.project_id, cited, rows, query, max_nodes, truncated)
    if totals:
        result["stats"].update({"total_nodes": totals["nodes"], "total_edges": totals["edges"]})
    return result


async def current_graph_node(db, *, runtime, authorized, node_id):
    graph = await build_current_graph(db, runtime=runtime, authorized=authorized, focus_node_id=node_id)
    if graph["state"] not in ("ok", "no_matches", "not_extracted"):
        return graph
    node = next((node for node in graph["nodes"] if node["id"] == node_id), None)
    if node is None:
        return None
    nodes = {item["id"]: item for item in graph["nodes"]}
    claims, relations = [], []
    for edge in graph["edges"]:
        provenance = {key: edge[key] for key in (
            "citation", "cite_as", "evidence_key", "source_title", "source_url", "section", "source_id", "revision_id"
        )}
        outgoing = edge["source"] == node_id
        peer = nodes[edge["target"] if outgoing else edge["source"]]
        relations.append({
            "edge_type": edge["edge_type"], "direction": "out" if outgoing else "in",
            "peer_id": peer["id"], "peer_name": peer["display_name"], "peer_type": peer["node_type"],
            "description": edge["description"], **provenance,
        })
        claims.append({
            "claim_type": edge["edge_type"], "statement": edge["description"],
            "valid_from_label": None, "valid_until_label": None, **provenance,
        })
    return {
        **node, "store": "extracted_graph", "workspace_id": authorized.project_id, "state": "ok",
        "truncated": graph["truncated"], "status": "extracted", "properties": {}, "aliases": [],
        "source_refs": sorted({edge["cite_as"] for edge in graph["edges"]}),
        "claims": claims, "relations": relations,
    }
