from __future__ import annotations

from typing import Any


def summarize_flow_process(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a compact executable-process view for LLM/tool catalogs and admins."""
    nodes = [dict(node) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    edges = [_normalize_edge(edge) for edge in definition.get("edges") or [] if isinstance(edge, dict)]
    ordered_ids = _ordered_node_ids(nodes, edges)
    node_map = {str(node.get("id") or ""): node for node in nodes}
    return [
        _summarize_node(node_map[node_id], index=index + 1, outgoing_edges=_outgoing_edges(node_id, edges))
        for index, node_id in enumerate(ordered_ids)
        if node_id in node_map
    ]


def render_flow_process_for_tool_description(process_steps: list[dict[str, Any]], *, limit: int = 6) -> str:
    if not process_steps:
        return ""
    rendered: list[str] = []
    for step in process_steps[: max(1, limit)]:
        rendered.append(_render_step(step))
    if len(process_steps) > limit:
        rendered.append(f"... {len(process_steps) - limit} more step(s)")
    return "Process: " + " -> ".join(rendered)


def _summarize_node(
    node: dict[str, Any],
    *,
    index: int,
    outgoing_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    node_type = str(node.get("type") or "").strip() or "unknown"
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    step: dict[str, Any] = {
        "index": index,
        "node_id": str(node.get("id") or "").strip(),
        "type": node_type,
        "label": str(node.get("label") or node_type).strip(),
    }
    tool_names = _node_tool_names(config)
    if tool_names:
        step["tools"] = tool_names
    policy = str(config.get("policy") or config.get("quality_gate") or config.get("approval_policy") or "").strip()
    if policy:
        step["policy"] = policy
    if node_type == "router":
        step["branches"] = _router_branches(config, outgoing_edges)
    return step


def _node_tool_names(config: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("tool", "tool_name"):
        value = str(config.get(key) or "").strip()
        if value:
            names.append(value)
    for value in config.get("allowed_tools") or []:
        name = str(value or "").strip()
        if name:
            names.append(name)
    return list(dict.fromkeys(names))[:12]


def _router_branches(config: dict[str, Any], outgoing_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    routes = config.get("routes") if isinstance(config.get("routes"), list) else []
    for route in routes:
        if not isinstance(route, dict):
            continue
        branches.append(
            {
                "route": str(route.get("route") or route.get("target") or "default").strip() or "default",
                "when": route.get("when") if isinstance(route.get("when"), dict) else {},
            }
        )
    for edge in outgoing_edges:
        condition = edge.get("condition")
        if condition:
            branches.append({"route": str(condition), "target": edge.get("target")})
    if not branches:
        default_route = str(config.get("default_route") or "default").strip() or "default"
        branches.append({"route": default_route})
    return branches[:8]


def _render_step(step: dict[str, Any]) -> str:
    label = str(step.get("label") or step.get("type") or "step").strip()
    node_type = str(step.get("type") or "").replace("_", " ")
    tools = [str(item) for item in step.get("tools") or [] if str(item).strip()]
    branches = step.get("branches") if isinstance(step.get("branches"), list) else []
    suffixes: list[str] = []
    if tools:
        suffixes.append("tools " + ", ".join(f"`{tool}`" for tool in tools[:4]))
    if branches:
        suffixes.append("branches " + ", ".join(_branch_label(branch) for branch in branches[:4]))
    suffix = f" ({'; '.join(suffixes)})" if suffixes else ""
    return f"{int(step.get('index') or 0)}. {label} [{node_type}]{suffix}"


def _branch_label(branch: Any) -> str:
    if not isinstance(branch, dict):
        return str(branch)
    route = str(branch.get("route") or "default")
    target = str(branch.get("target") or "").strip()
    condition = _condition_label(branch.get("when"))
    label = f"{route} if {condition}" if condition else route
    return f"{label}->{target}" if target else label


def _condition_label(condition: Any) -> str:
    if not isinstance(condition, dict):
        return ""
    field = str(condition.get("field") or "").strip()
    if not field:
        return ""
    operator = str(condition.get("operator") or "").strip()
    if operator:
        return f"{field} {operator} {condition.get('value')}"
    for key in ("equals", "not_equals", "exists", "in", "not_in", "contains", "gt", "gte", "lt", "lte", "truthy"):
        if key in condition:
            return f"{field} {key} {condition.get(key)}"
    return field


def _ordered_node_ids(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    node_ids = [str(node.get("id") or "") for node in nodes if str(node.get("id") or "")]
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in outgoing and target in incoming:
            outgoing[source].append(target)
            incoming[target] += 1
    ready = [node_id for node_id in node_ids if incoming.get(node_id, 0) == 0]
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        if node_id in ordered:
            continue
        ordered.append(node_id)
        for target in outgoing.get(node_id, []):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return ordered + [node_id for node_id in node_ids if node_id not in ordered]


def _outgoing_edges(node_id: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if edge.get("source") == node_id]


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": _edge_value(edge, "source_node_id", "from_node_id", "source", "from"),
        "target": _edge_value(edge, "target_node_id", "to_node_id", "target", "to"),
        "condition": edge.get("condition"),
    }


def _edge_value(edge: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(edge.get(key) or "").strip()
        if value:
            return value
    return ""
