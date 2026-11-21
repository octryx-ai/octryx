"""AWS network path analyzer connector tool."""

from __future__ import annotations

from collections import deque
from typing import Any

from ..context import ToolContext
from .aws_topology import build_aws_topology_snapshot
from .aws_topology_common import bounded_int
from .common import _string

PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}
MAX_PATHS = 10


def _nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("nodes")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _edges(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("edges")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _node_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _nodes(snapshot) if item.get("id")}


def _resolve_node_id(snapshot: dict[str, Any], *, node_id: str, label: str) -> str | None:
    if node_id:
        return node_id if node_id in _node_map(snapshot) else None
    if not label:
        return None
    for node in _nodes(snapshot):
        if _string(node.get("label")) == label or _string(node.get("id")) == label:
            return str(node.get("id"))
    return None


def _adjacency(snapshot: dict[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    graph: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for edge in _edges(snapshot):
        source = _string(edge.get("source"))
        target = _string(edge.get("target"))
        if not source or not target:
            continue
        graph.setdefault(source, []).append((target, edge))
        graph.setdefault(target, []).append((source, edge))
    return graph


def _find_paths(snapshot: dict[str, Any], source_id: str, target_id: str, *, max_depth: int) -> list[list[str]]:
    graph = _adjacency(snapshot)
    paths = []
    queue = deque([(source_id, [source_id])])
    while queue and len(paths) < MAX_PATHS:
        current, path = queue.popleft()
        if len(path) > max_depth + 1:
            continue
        if current == target_id:
            paths.append(path)
            continue
        for next_id, _edge in graph.get(current, []):
            if next_id in path:
                continue
            queue.append((next_id, [*path, next_id]))
    return paths


def _edge_between(snapshot: dict[str, Any], left: str, right: str) -> dict[str, Any] | None:
    for edge in _edges(snapshot):
        source = _string(edge.get("source"))
        target = _string(edge.get("target"))
        if {source, target} == {left, right}:
            return edge
    return None


def _serialize_path(snapshot: dict[str, Any], path: list[str]) -> dict[str, Any]:
    nodes = _node_map(snapshot)
    hops = []
    evidence = []
    for index, node_id in enumerate(path):
        node = nodes.get(node_id, {})
        hop: dict[str, Any] = {
            "node_id": node_id,
            "label": node.get("label"),
            "type": node.get("type"),
            "service": node.get("service"),
        }
        if index > 0:
            edge = _edge_between(snapshot, path[index - 1], node_id) or {}
            hop["via_edge"] = {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "type": edge.get("type"),
                "service": edge.get("service"),
                "attributes": edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {},
            }
            evidence.extend(list(edge.get("evidence") or []))
        evidence.extend(list(node.get("evidence") or []))
        hops.append(hop)
    return {"hop_count": max(0, len(path) - 1), "hops": hops, "evidence": evidence}


def _exposure_notes(snapshot: dict[str, Any], source_id: str, target_id: str) -> list[dict[str, Any]]:
    nodes = _node_map(snapshot)
    source = nodes.get(source_id, {})
    target = nodes.get(target_id, {})
    notes = []
    if source.get("label") in PUBLIC_CIDRS:
        notes.append(
            {
                "severity": "high",
                "message": f"Source is public CIDR {source.get('label')}; any path should be reviewed as exposure.",
            }
        )
    target_attrs = target.get("attributes") if isinstance(target.get("attributes"), dict) else {}
    if target.get("type") == "load_balancer" and target_attrs.get("scheme") == "internet-facing":
        notes.append({"severity": "medium", "message": "Target is an internet-facing load balancer."})
    return notes


async def analyze_aws_network_path(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    topology_source = "provided" if topology else "collected"
    if topology is None:
        snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
        topology = await build_aws_topology_snapshot(context, snapshot_params)

    source_id = _resolve_node_id(
        topology,
        node_id=_string(params.get("source_node_id")),
        label=_string(params.get("source_label")),
    )
    target_id = _resolve_node_id(
        topology,
        node_id=_string(params.get("target_node_id")),
        label=_string(params.get("target_label")),
    )
    if not source_id or not target_id:
        return {
            "status": "invalid_input",
            "error": "source and target must resolve to topology nodes",
            "source_resolved": source_id,
            "target_resolved": target_id,
        }

    max_depth = bounded_int(params.get("max_depth"), default=6, maximum=12)
    raw_paths = _find_paths(topology, source_id, target_id, max_depth=max_depth)
    paths = [_serialize_path(topology, path) for path in raw_paths]
    return {
        "status": "ok",
        "topology_source": topology_source,
        "source_node_id": source_id,
        "target_node_id": target_id,
        "reachability": "path_found" if paths else "no_static_path_found",
        "analysis_basis": "static_topology_relationships_no_active_probe",
        "max_depth": max_depth,
        "path_count": len(paths),
        "paths": paths,
        "exposure_notes": _exposure_notes(topology, source_id, target_id),
        "warnings": list(topology.get("warnings") or []),
    }


class AwsNetworkPathAnalyzerTool:
    name = "aws_network_path_analyzer"
    description = (
        "Analyze static AWS topology relationships between two nodes without sending active network traffic. "
        "Use for explainable reachability and exposure investigations."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await analyze_aws_network_path(context, params or {})
