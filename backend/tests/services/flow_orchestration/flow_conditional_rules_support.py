"""Shared router flow builder for the authored router condition tests."""

from __future__ import annotations

# --- authoring validation and API ---------------------------------------------------------


def _router_flow(rules: list, *, default_route: str = "b", connections: list | None = None) -> dict:
    connections = connections or [("a", "route:a"), ("b", "route:b")]
    nodes = [
        {"id": "input", "type": "trigger"},
        {"id": "router", "type": "router", "config": {"routes": rules, "default_route": default_route}},
        *[{"id": target, "type": "tool_step", "config": {"tool": f"{target}_tool", "arguments": {}}}
          for target, _ in connections],
        {"id": "out", "type": "output"},
    ]
    edges = [
        {"source_node_id": "input", "target_node_id": "router"},
        *[{"source_node_id": "router", "target_node_id": target, "condition": condition}
          for target, condition in connections],
        *[{"source_node_id": target, "target_node_id": "out"} for target, _ in connections],
    ]
    return {"schema_version": "2.0", "nodes": nodes, "edges": edges}
