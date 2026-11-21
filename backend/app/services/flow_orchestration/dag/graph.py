"""Graph shape of a flow definition: edges, order, reachability and how inputs flow along edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..router_branches import select_router_targets
from .conditions import _router_edge_condition_matches
from .paths import _read_path, _write_path


@dataclass(frozen=True)
class FlowGraph:
    """A flow definition's nodes and normalized edges in execution order."""

    definition: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    ordered_node_ids: list[str]
    node_map: dict[str, dict[str, Any]]


def parse_flow_graph(version: Any) -> FlowGraph:
    definition = dict(version.definition_json or {})
    nodes = [dict(node) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    edges = [_normalize_edge(edge) for edge in definition.get("edges") or [] if isinstance(edge, dict)]
    ordered_node_ids = topological_sort_nodes(nodes, edges)
    node_map = {str(node.get("id") or ""): node for node in nodes}
    return FlowGraph(definition, nodes, edges, ordered_node_ids, node_map)


def _reachable_downstream_node_ids(start_node_id: str, edges: list[dict[str, Any]]) -> set[str]:
    normalized_edges = [_normalize_edge(edge) for edge in edges]
    reachable = {start_node_id}
    queue = [start_node_id]
    while queue:
        current = queue.pop(0)
        for edge in normalized_edges:
            if edge["source"] != current or edge["target"] in reachable:
                continue
            reachable.add(edge["target"])
            queue.append(edge["target"])
    return reachable


def topological_sort_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    node_ids = [str(node.get("id") or "").strip() for node in nodes if str(node.get("id") or "").strip()]
    node_id_set = set(node_ids)
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    in_degree: dict[str, int] = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source in node_id_set and target in node_id_set:
            successors[source].append(target)
            in_degree[target] += 1
    queue = [node_id for node_id in node_ids if in_degree[node_id] == 0]
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for target in successors[current]:
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)
    return ordered


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(edge.get("source_node_id") or edge.get("from_node_id") or edge.get("from") or "").strip(),
        "target": str(edge.get("target_node_id") or edge.get("to_node_id") or edge.get("to") or "").strip(),
        "source_field": str(edge.get("source_field") or "").strip(),
        "target_field": str(edge.get("target_field") or "").strip(),
        "condition": edge.get("condition"),
    }


def _materialize_node_input(
    *,
    node_id: str,
    edges: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    initial_input: dict[str, Any],
) -> dict[str, Any]:
    incoming = [edge for edge in edges if edge["target"] == node_id and edge["source"] in outputs]
    if not incoming:
        return dict(initial_input)
    if len(incoming) == 1 and not incoming[0]["source_field"] and not incoming[0]["target_field"]:
        return dict(outputs.get(incoming[0]["source"], {}))
    materialized: dict[str, Any] = {}
    for edge in incoming:
        source_output = outputs.get(edge["source"], {})
        value = _read_path(source_output, edge["source_field"]) if edge["source_field"] else source_output
        target_field = edge["target_field"] or edge["source"]
        _write_path(materialized, target_field, value)
    return materialized


def _selected_router_targets(
    node: dict[str, Any],
    output: dict[str, Any],
    edges: list[dict[str, Any]],
) -> set[str] | None:
    if str(node.get("type") or "") != "router":
        return None
    node_id = str(node.get("id") or "")
    route = str(output.get("route") or "default")
    # No first-connection fallback: an unconnected branch fails the node as a configuration error.
    return select_router_targets(
        [edge for edge in edges if edge["source"] == node_id],
        lambda condition: _router_edge_condition_matches(condition, route=route, router_output=output),
    )


def _unselected_router_targets(node_id: str, edges: list[dict[str, Any]], selected_targets: set[str]) -> set[str]:
    return {edge["target"] for edge in edges if edge["source"] == node_id and edge["target"] not in selected_targets}


def _all_incoming_skipped(node_id: str, edges: list[dict[str, Any]], skipped: set[str]) -> bool:
    incoming = [edge for edge in edges if edge["target"] == node_id]
    return bool(incoming) and all(edge["source"] in skipped for edge in incoming)


def _last_output(outputs: dict[str, dict[str, Any]], ordered_node_ids: list[str]) -> dict[str, Any]:
    for node_id in reversed(ordered_node_ids):
        if node_id in outputs:
            return outputs[node_id]
    return {}
