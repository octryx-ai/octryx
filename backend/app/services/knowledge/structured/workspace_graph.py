"""The Workspace graph explorer over every layer: extracted (Graphiti) plus structured.

``layers`` selects what is read: ``extracted`` (the Graphiti facts of ``temporal/visualization``),
``manual``, ``configuration`` and ``operations``; empty means all. Extracted nodes come first, then
structured ones until ``max_nodes``; every node and edge names its ``layer``. A structured node id
(64 hex digits) focuses the structured layers, any other id the extracted graph. The payload keeps
the explorer contract (``nodes``, ``edges``, ``match_ids``, ``stats``) and adds ``layer_states``, so
an unconfigured extracted graph does not hide a built structured one.

Two additions:

- **Totals.** ``stats.total_nodes``/``total_edges`` are the whole visible graph (sum over the stores),
  ``stats.totals_by_store`` per store (``extracted``, ``structured``; null = not read or not answered).
- **Expand.** ``expand_node_id`` (+ ``current_node_ids``, the ids the client already shows) returns
  only that node's neighbourhood that is *new* to the view — nodes not in ``current_node_ids`` and
  the edges reaching them or the expanded node — with ``mode: "expand"`` and ``additive: true``, so
  the client merges instead of replacing. ``max_nodes`` bounds the new nodes.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from .explorer import structured_explorer
from .overview import structured_totals
from .profile_types import LAYERS

LAYER_EXTRACTED = "extracted"
ALL_LAYERS = (*LAYERS, LAYER_EXTRACTED)
STORE = "workspace_graph"
_STRUCTURED_ID = re.compile(r"^[0-9a-f]{64}$")


class UnknownLayerError(ValueError):
    """A requested layer the explorer does not know."""


def parse_layers(raw: str | None) -> tuple[str, ...]:
    items = tuple(item.strip() for item in (raw or "").split(",") if item.strip())
    if not items:
        return ALL_LAYERS
    if not set(items) <= set(ALL_LAYERS):
        raise UnknownLayerError()
    return tuple(layer for layer in ALL_LAYERS if layer in items)


def is_structured_id(node_id: str) -> bool:
    return bool(_STRUCTURED_ID.fullmatch(node_id or ""))


async def build_workspace_graph(
    db: AsyncSession,
    *,
    runtime,
    authorized: AuthorizedWorkspace,
    query: str = "",
    focus_node_id: str = "",
    max_nodes: int = 150,
    layers: tuple[str, ...] = ALL_LAYERS,
    expand_node_id: str = "",
    current_node_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if expand_node_id:
        return await _expand(db, runtime=runtime, authorized=authorized, node_id=expand_node_id,
                             current=current_node_ids, max_nodes=max_nodes, layers=layers)
    result = await _build(db, runtime=runtime, authorized=authorized, query=query, focus_node_id=focus_node_id,
                          max_nodes=max_nodes, layers=layers)
    result["mode"] = "focus" if focus_node_id else "query" if query.strip() else "overview"
    result["additive"] = False
    return result


async def _expand(db, *, runtime, authorized, node_id, current, max_nodes, layers) -> dict[str, Any]:
    """The focus window of ``node_id``, minus what the client already shows; budget for new nodes."""
    from ..temporal.visualization_queries import MAX_NODES

    budget = min(MAX_NODES, max_nodes + len(current))
    result = await _build(db, runtime=runtime, authorized=authorized, query="", focus_node_id=node_id,
                          max_nodes=budget, layers=layers)
    known = set(current) | {node_id}
    fresh = [node for node in result["nodes"] if node["id"] not in known]
    kept_new = fresh[:max_nodes]
    present = known | {node["id"] for node in kept_new}
    edges = [edge for edge in result["edges"] if edge["source"] in present and edge["target"] in present
             and ({edge["source"], edge["target"]} - set(current))]
    result["truncated"] = bool(result["truncated"] or len(fresh) > max_nodes)
    result["nodes"], result["edges"] = kept_new, edges
    result["stats"].update({
        "shown_nodes": len(kept_new), "shown_edges": len(edges),
        "node_types": dict(Counter(node["node_type"] for node in kept_new)),
        "edge_types": dict(Counter(edge["edge_type"] for edge in edges)),
        "layers": dict(Counter(node.get("layer", LAYER_EXTRACTED) for node in kept_new)),
    })
    if result["state"] == "ok" and not edges:
        result["state"] = "no_matches"  # nothing new around this node
    result.update({"mode": "expand", "additive": True, "expand_node_id": node_id})
    return result


async def _build(db, *, runtime, authorized, query, focus_node_id, max_nodes, layers) -> dict[str, Any]:
    from ..temporal.visualization import _empty, build_current_graph

    structured_focus = is_structured_id(focus_node_id)
    folded = query.strip().casefold()[:500]
    extracted = None
    if LAYER_EXTRACTED in layers and not structured_focus and runtime is not None:
        extracted = await build_current_graph(db, runtime=runtime, authorized=authorized, query=query,
                                              focus_node_id=focus_node_id, max_nodes=max_nodes)
    structured = None
    wanted = tuple(layer for layer in layers if layer in LAYERS)
    if wanted and (not focus_node_id or structured_focus):
        structured = await structured_explorer(db, authorized=authorized, query=query, focus_node_id=focus_node_id,
                                               max_nodes=max_nodes, layers=wanted)
    result = extracted or _empty(authorized.project_id, "not_requested", query=folded)
    for item in (*result["nodes"], *result["edges"]):
        item.setdefault("layer", LAYER_EXTRACTED)
    if structured is not None:
        present = {node["id"] for node in result["nodes"]}
        for node in structured["nodes"]:
            if node["id"] not in present and len(present) < max_nodes:
                result["nodes"].append(node)
                present.add(node["id"])
        added = [edge for edge in structured["edges"] if edge["source"] in present and edge["target"] in present]
        result["edges"].extend(added)
        result["truncated"] = bool(result["truncated"] or structured["truncated"]
                                   or len(added) < len(structured["edges"]))
    nodes, edges = result["nodes"], result["edges"]
    if folded:
        result["match_ids"] = [node["id"] for node in nodes if node.get("matched")]
    result["stats"].update({
        "shown_nodes": len(nodes), "shown_edges": len(edges),
        "matched_nodes": len(result["match_ids"]) if folded else None,
        "node_types": dict(Counter(node["node_type"] for node in nodes)),
        "edge_types": dict(Counter(edge["edge_type"] for edge in edges)),
        "layers": dict(Counter(node["layer"] for node in nodes)),
    })
    extracted_state = extracted["state"] if extracted else "not_requested"
    structured_state = structured["state"] if structured else "not_requested"
    result["layer_states"] = {LAYER_EXTRACTED: extracted_state, "structured": structured_state}
    if nodes:
        result["state"] = "ok"
    elif "no_matches" in (extracted_state, structured_state):
        result["state"] = "no_matches"
    elif extracted is not None and extracted_state not in ("ok", "not_extracted"):
        result["state"] = extracted_state
    else:
        result["state"] = "not_extracted"
    result["store"] = STORE
    extracted_counts = ({"nodes": result["stats"]["total_nodes"], "edges": result["stats"]["total_edges"]}
              if extracted is not None and extracted["stats"].get("total_nodes") is not None else None)
    structured_counts = await structured_totals(db, authorized, wanted) if wanted else None
    by_store = {"extracted": extracted_counts, "structured": structured_counts}
    known = [counts for counts in by_store.values() if counts is not None]
    result["stats"].update({
        "totals_by_store": by_store,
        "total_nodes": sum(counts["nodes"] for counts in known) if known else None,
        "total_edges": sum(counts["edges"] for counts in known) if known else None,
    })
    return result


__all__ = ["ALL_LAYERS", "LAYER_EXTRACTED", "STORE", "UnknownLayerError", "build_workspace_graph",
           "is_structured_id", "parse_layers"]
