"""Relationship (edge) cells, labels and styles for AWS topology diagrams."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _truncate_label, _xml_value


def _edge_cells(
    selected_edges: list[dict[str, Any]],
    selected_nodes: list[dict[str, Any]],
    node_refs: dict[int, str],
) -> list[str]:
    ref_by_node_id: dict[str, str] = {}
    known_refs: set[str] = set()
    for node in selected_nodes:
        ref = node_refs[id(node)]
        known_refs.add(ref)
        original_id = str(node.get("id") or "").strip()
        if original_id:
            ref_by_node_id[original_id] = ref

    cells: list[str] = []
    used_pairs: set[tuple[str, str, str, str]] = set()
    edge_index = 1
    for edge in selected_edges:
        source = _edge_endpoint(edge, "source", ref_by_node_id, known_refs)
        target = _edge_endpoint(edge, "target", ref_by_node_id, known_refs)
        if not source or not target or source == target:
            continue
        edge_type = str(edge.get("type") or "related_to").strip() or "related_to"
        value = _edge_value(edge_type, edge)
        pair = (source, target, edge_type, value)
        if pair in used_pairs:
            continue
        used_pairs.add(pair)
        cells.append(
            f'<mxCell id="rel_{edge_index}" value="{value}" '
            f'style="{_edge_style(edge_type)}" edge="1" parent="1" source="{source}" target="{target}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        edge_index += 1
    return cells


def _edge_value(edge_type: str, edge: dict[str, Any]) -> str:
    attrs = edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
    label = edge_type.replace("_", " ")
    if edge_type in {"allows_ingress_to", "allows_egress_to"}:
        direction = "ingress" if edge_type == "allows_ingress_to" else "egress"
        label = f"{direction} {_format_protocol_ports(attrs)}".strip()
    elif edge_type == "uses_security_group":
        label = "uses security group"
    elif edge_type == "routes_to" and attrs.get("listeners"):
        listeners = [str(item) for item in (attrs.get("listeners") or []) if str(item)]
        label = f"routes to ({', '.join(listeners[:3])})"
    elif edge_type == "routes_to" and attrs.get("destination"):
        label = f"routes to {attrs.get('destination')}"
    elif edge_type == "serves":
        label = "serves"
    elif edge_type == "connects_to":
        label = "connects to"
    return _xml_value(_truncate_label(label, 64))


def _format_protocol_ports(attrs: dict[str, Any]) -> str:
    protocol = str(attrs.get("protocol") or "").strip()
    from_port = attrs.get("from_port")
    to_port = attrs.get("to_port")
    if protocol == "-1":
        return "all traffic"
    if from_port is None and to_port is None:
        return protocol or "traffic"
    if from_port == to_port:
        return f"{protocol}/{from_port}" if protocol else str(from_port)
    return f"{protocol}/{from_port}-{to_port}" if protocol else f"{from_port}-{to_port}"


def _edge_style(edge_type: str) -> str:
    base = "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;fontSize=9;"
    if edge_type == "uses_security_group":
        return base + "strokeWidth=2;strokeColor=#dc2626;fontColor=#991b1b;"
    if edge_type == "allows_ingress_to":
        return base + "strokeWidth=2;strokeColor=#ef4444;fontColor=#991b1b;dashed=1;"
    if edge_type == "allows_egress_to":
        return base + "strokeWidth=2;strokeColor=#f97316;fontColor=#9a3412;dashed=1;"
    if edge_type == "protects":
        return base + "strokeWidth=2;strokeColor=#b91c1c;fontColor=#7f1d1d;"
    if edge_type == "routes_to":
        return base + "strokeWidth=2;strokeColor=#2563eb;fontColor=#1e3a8a;"
    # derived traffic-flow edges: solid green, clearly a logical flow
    if edge_type == "serves":
        return base + "strokeWidth=2;strokeColor=#0d9488;fontColor=#0f766e;"
    if edge_type == "connects_to":
        return base + "strokeWidth=2;strokeColor=#7c3aed;fontColor=#5b21b6;dashed=1;"
    # deep wiring: DNS chain (sky blue) and event wiring (pink)
    if edge_type == "resolves_to":
        return base + "strokeWidth=2;strokeColor=#0ea5e9;fontColor=#0369a1;"
    if edge_type == "triggers":
        return base + "strokeWidth=2;strokeColor=#E7157B;fontColor=#9d174d;"
    if edge_type == "delivers_to":
        return base + "strokeWidth=2;strokeColor=#E7157B;fontColor=#9d174d;dashed=1;"
    return base + "strokeWidth=1;strokeColor=#64748b;fontColor=#475569;dashed=1;opacity=55;"



def _edge_endpoint(
    edge: dict[str, Any],
    side: str,
    ref_by_node_id: dict[str, str],
    known_refs: set[str],
) -> str:
    ref = str(edge.get(f"{side}_ref") or "").strip()
    if ref in known_refs:
        return ref
    original_id = str(edge.get(side) or "").strip()
    return ref_by_node_id.get(original_id, "")

