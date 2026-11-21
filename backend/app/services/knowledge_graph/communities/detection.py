"""Deterministic community detection and structural summaries."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

_MAX_COMMUNITY_SIZE = 40


def _community_key(node_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(node_ids)).encode("utf-8")).hexdigest()
    return f"c-{digest[:16]}"


def _connected_components(nodes: list[Any], adjacency: dict[str, set[str]]) -> list[list[str]]:
    seen: set[str] = set()
    components: list[list[str]] = []
    for node in sorted(nodes, key=lambda item: item.id):
        if node.id in seen:
            continue
        stack, component = [node.id], []
        seen.add(node.id)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, ())):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if len(component) > 1:  # singletons are noise, not communities
            components.append(sorted(component))
    return components


def _split_by_hubs(component: list[str], adjacency: dict[str, set[str]], max_size: int) -> list[list[str]]:
    # Split an oversized component around its highest-degree hubs: each hub
    # claims itself + its direct neighbors (deterministic order).
    result: list[list[str]] = []
    remaining = set(component)
    hubs = sorted(component, key=lambda nid: (-len(adjacency.get(nid, ())), nid))
    for hub in hubs:
        if hub not in remaining:
            continue
        cluster = [hub] + [n for n in sorted(adjacency.get(hub, ())) if n in remaining]
        cluster = cluster[:max_size]
        remaining -= set(cluster)
        if len(cluster) > 1:
            result.append(sorted(cluster))
    leftovers = sorted(remaining)
    if len(leftovers) > 1:
        result.append(leftovers)
    return result


def detect_communities(
    nodes: list[Any],
    edges: list[Any],
    *,
    max_size: int = _MAX_COMMUNITY_SIZE,
) -> list[list[str]]:
    """Deterministic clustering: connected components, hub-split when oversized."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    node_ids = {node.id for node in nodes}
    for edge in edges:
        if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
            adjacency[edge.source_node_id].add(edge.target_node_id)
            adjacency[edge.target_node_id].add(edge.source_node_id)

    result: list[list[str]] = []
    for component in _connected_components(nodes, adjacency):
        if len(component) <= max_size:
            result.append(component)
            continue
        result.extend(_split_by_hubs(component, adjacency, max_size))
    return result


def _structural_summary(members: list[Any], edges: list[Any]) -> str:
    member_ids = {node.id for node in members}
    by_type: dict[str, list[str]] = defaultdict(list)
    for node in members:
        by_type[node.node_type].append(node.display_name)
    type_lines = "; ".join(
        f"{node_type}: {', '.join(sorted(names)[:8])}" for node_type, names in sorted(by_type.items())
    )
    edge_types = sorted(
        {
            edge.edge_type
            for edge in edges
            if edge.source_node_id in member_ids and edge.target_node_id in member_ids
        }
    )
    return (
        f"Cluster of {len(members)} entities. {type_lines}. "
        f"Relationship types: {', '.join(edge_types) or 'none'}."
    )
