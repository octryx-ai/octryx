"""Banded flow layout for AWS detail diagrams (selections without a VPC)."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _xml_value
from .aws_structural_autolayout import wrap_grid
from .aws_structural_cells import _IconRenderer
from .aws_topology_cells import _legend_cell, _node_refs, _title_cell
from .aws_topology_edges import _edge_cells, _format_protocol_ports

_SLOT_W = 136
_SLOT_H = 124
_GAP_X = 16
_GAP_Y = 12
_BAND_GAP = 26
_BAND_PAD = 14
_BAND_TITLE_H = 30
_CANVAS_X = 40
_CANVAS_Y = 190
_MAX_COLUMNS = 9
_MIN_COLUMNS = 4
# Unwired same-type nodes stay individually named up to this count; only
# larger groups fold into one counted node.
_MAX_UNWIRED_NAMED = 12

# Role bands in traffic order: sources on top, data stores at the bottom.
_BAND_TITLES = {
    0: "Traffic sources",
    1: "Security groups",
    2: "Edge and ingress",
    3: "Load balancing and routing",
    4: "Compute",
    5: "Integration and clusters",
    6: "Data stores",
}
_BAND_STYLES = {
    0: ("#FDF2F2", "#B45309"),
    1: ("#FEF2F2", "#DD344C"),
    2: ("#F5F3FF", "#8C4FFF"),
    3: ("#F5F3FF", "#8C4FFF"),
    4: ("#FFF7ED", "#ED7100"),
    5: ("#FDF4FF", "#E7157B"),
    6: ("#FAF5FF", "#C925D1"),
}
_TYPE_BANDS = {
    "cidr": 0,
    "security_group": 1,
    "waf_web_acl": 2,
    "cloudfront_distribution": 2,
    "route53_zone": 2,
    "internet_gateway": 2,
    "nat_gateway": 2,
    "api_gateway": 3,
    "load_balancer": 3,
    "target_group": 3,
    "route_table": 3,
    "subnet": 3,
    "eks_nodegroup": 4,
    "autoscaling_group": 4,
    "lambda_function": 4,
    "ecs_service": 4,
    "ec2_instance": 4,
    "step_function": 4,
    "eks_cluster": 5,
    "ecs_cluster": 5,
    "sqs_queue": 5,
    "sns_topic": 5,
    "eventbridge_bus": 5,
    "rds_proxy": 6,
    "rds_instance": 6,
    "rds_cluster": 6,
    "dynamodb_table": 6,
    "elasticache_cluster": 6,
    "s3_bucket": 6,
    "efs_file_system": 6,
}
_DEFAULT_BAND = 5


def render_detail_topology_xml(
    *,
    title: str,
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    shape_lookup: dict[str, str],
    prefix: str,
    omitted_edge_count: int = 0,
) -> str:
    edges, egress_note = _summarize_egress_all(selected_edges)
    nodes = _drop_unwired_cidrs(selected_nodes, edges)
    nodes, edges, folded_note = _fold_identical_wiring(nodes, edges)
    notes = " | ".join(note for note in (folded_note, egress_note) if note)

    bands = _band_membership(nodes)
    order = _barycenter_order(bands, nodes, edges)
    columns = _column_count(bands)
    inner_width = columns * _SLOT_W + (columns - 1) * _GAP_X
    band_width = inner_width + 2 * _BAND_PAD

    icon = _IconRenderer(shape_lookup, prefix)
    node_refs = _node_refs(nodes)
    ref_of = {str(node.get("ref") or node.get("id") or "").strip(): node for node in nodes}
    cells: list[str] = [
        _title_cell(title, topology_result),
        _legend_cell(
            topology_result, selected_nodes, selected_edges, omitted_edge_count=omitted_edge_count
        ),
    ]
    if notes:
        cells.append(_note_cell(notes, band_width))

    cursor_y = _CANVAS_Y
    for band in sorted(bands):
        member_refs = order[band]
        rects, _, inner_h = wrap_grid(
            [(_SLOT_W, _SLOT_H)] * len(member_refs),
            max_width=inner_width,
            gap_x=_GAP_X,
            gap_y=_GAP_Y,
        )
        band_id = f"band_{band}"
        band_h = _BAND_TITLE_H + inner_h + _BAND_PAD
        fill, stroke = _BAND_STYLES.get(band, ("#F8FAFC", "#5A6B86"))
        label = f"{_BAND_TITLES.get(band, 'Resources')} ({len(member_refs)})"
        cells.append(
            f'<mxCell id="{band_id}" value="{_xml_value(label)}" '
            'style="rounded=1;arcSize=4;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;'
            "verticalAlign=top;align=left;spacingLeft=12;container=1;collapsible=0;"
            f'recursiveResize=0;fillColor={fill};strokeColor={stroke};fontColor={stroke};" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{_CANVAS_X}" y="{cursor_y}" width="{band_width}" height="{band_h}" as="geometry"/>'
            "</mxCell>"
        )
        for member_ref, (x, y, _w, _h) in zip(member_refs, rects):
            node = ref_of[member_ref]
            cells.append(
                icon.cell(node, node_refs[id(node)], band_id, _BAND_PAD + x, _BAND_TITLE_H + y)
            )
        cursor_y += band_h + _BAND_GAP

    cells.extend(_edge_cells(edges, nodes, node_refs))
    return "".join(cells)


def _summarize_egress_all(
    selected_edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    kept: list[dict[str, Any]] = []
    dropped = 0
    for edge in selected_edges:
        edge_type = str(edge.get("type") or "").strip()
        attrs = edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
        if edge_type == "allows_egress_to" and _format_protocol_ports(attrs) == "all traffic":
            dropped += 1
            continue
        kept.append(edge)
    note = f"{dropped} egress-all-traffic rules summarized (not drawn)" if dropped else ""
    return kept, note


def _drop_unwired_cidrs(
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    wired: set[str] = set()
    for edge in selected_edges:
        for side in ("source", "target"):
            ref = str(edge.get(f"{side}_ref") or edge.get(side) or "").strip()
            if ref:
                wired.add(ref)
    return [
        node
        for node in selected_nodes
        if str(node.get("type") or "").strip() != "cidr"
        or str(node.get("ref") or node.get("id") or "").strip() in wired
    ]


def _fold_identical_wiring(
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    signatures: dict[str, set[tuple[str, str, str, str]]] = {}
    for edge in selected_edges:
        edge_type = str(edge.get("type") or "").strip()
        source = str(edge.get("source_ref") or edge.get("source") or "").strip()
        target = str(edge.get("target_ref") or edge.get("target") or "").strip()
        ports = _format_protocol_ports(
            edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
        )
        if source:
            signatures.setdefault(source, set()).add(("out", edge_type, target, ports))
        if target:
            signatures.setdefault(target, set()).add(("in", edge_type, source, ports))

    groups: dict[tuple[str, frozenset], list[dict[str, Any]]] = {}
    for node in selected_nodes:
        ref = str(node.get("ref") or node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        key = (node_type, frozenset(signatures.get(ref, set())))
        groups.setdefault(key, []).append(node)

    alias: dict[str, str] = {}
    folded_nodes: list[dict[str, Any]] = []
    folded_count = 0
    for (node_type, signature), members in groups.items():
        # identical wiring folds; "no wiring at all" is also identical wiring
        # Unwired resources ARE the content of data-style details: show them
        # by name up to a readable cap instead of collapsing to one blob.
        if len(members) < 2 or (not signature and len(members) <= _MAX_UNWIRED_NAMED):
            folded_nodes.extend(members)
            continue
        members = sorted(
            members, key=lambda item: str(item.get("label") or item.get("ref") or "")
        )
        representative = dict(members[0])
        rep_ref = str(representative.get("ref") or representative.get("id") or "").strip()
        names = [str(item.get("label") or "").strip() for item in members]
        attributes = dict(representative.get("attributes") or {})
        attributes["summary_count"] = len(members)
        representative["attributes"] = attributes
        # Type-based fold label ("25 x DynamoDB tables"), never the first
        # member's name ("25 x .provider_metadata"); CIDRs keep the address
        # because it IS the information.
        if node_type == "cidr":
            representative["label"] = f"{len(members)} x {names[0]}"
        else:
            from .aws_inventory_board import _TYPE_LABELS

            type_label = _TYPE_LABELS.get(node_type, node_type.replace("_", " "))
            representative["label"] = f"{len(members)} x {type_label}"
        folded_nodes.append(representative)
        folded_count += len(members) - 1
        for member in members[1:]:
            member_ref = str(member.get("ref") or member.get("id") or "").strip()
            if member_ref:
                alias[member_ref] = rep_ref

    seen: set[tuple[str, str, str, str]] = set()
    folded_edges: list[dict[str, Any]] = []
    for edge in selected_edges:
        source = str(edge.get("source_ref") or edge.get("source") or "").strip()
        target = str(edge.get("target_ref") or edge.get("target") or "").strip()
        new_source, new_target = alias.get(source, source), alias.get(target, target)
        edge_type = str(edge.get("type") or "").strip()
        ports = _format_protocol_ports(
            edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
        )
        key = (new_source, new_target, edge_type, ports)
        if new_source == new_target or key in seen:
            continue
        seen.add(key)
        if new_source != source or new_target != target:
            edge = dict(edge)
            edge["source_ref"], edge["target_ref"] = new_source, new_target
            edge.pop("source", None)
            edge.pop("target", None)
        folded_edges.append(edge)

    note = (
        f"{folded_count} nodes with identical wiring are folded into counted nodes"
        if folded_count
        else ""
    )
    return folded_nodes, folded_edges, note


def _band_membership(nodes: list[dict[str, Any]]) -> dict[int, list[str]]:
    bands: dict[int, list[str]] = {}
    for node in nodes:
        ref = str(node.get("ref") or node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        bands.setdefault(_TYPE_BANDS.get(node_type, _DEFAULT_BAND), []).append(ref)
    return bands


def _barycenter_order(
    bands: dict[int, list[str]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[int, list[str]]:
    label_of = {
        str(node.get("ref") or node.get("id") or "").strip(): str(node.get("label") or "")
        for node in nodes
    }
    neighbors: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("source_ref") or edge.get("source") or "").strip()
        target = str(edge.get("target_ref") or edge.get("target") or "").strip()
        if source and target and source != target:
            neighbors.setdefault(source, set()).add(target)
            neighbors.setdefault(target, set()).add(source)

    ordered = {
        band: sorted(members, key=lambda ref: label_of.get(ref, ref))
        for band, members in bands.items()
    }
    slot = {ref: index for members in ordered.values() for index, ref in enumerate(members)}

    def _sweep(band_sequence: list[int]) -> None:
        for band in band_sequence:
            def _score(ref: str) -> tuple[float, str]:
                anchor_slots = [
                    slot[peer] for peer in neighbors.get(ref, set()) if peer in slot and peer != ref
                ]
                if not anchor_slots:
                    return (float("inf"), label_of.get(ref, ref))
                return (sum(anchor_slots) / len(anchor_slots), label_of.get(ref, ref))

            ordered[band] = sorted(ordered[band], key=_score)
            for index, ref in enumerate(ordered[band]):
                slot[ref] = index

    band_order = sorted(bands)
    _sweep(band_order)
    _sweep(list(reversed(band_order)))
    _sweep(band_order)
    return ordered


def _column_count(bands: dict[int, list[str]]) -> int:
    largest = max((len(members) for members in bands.values()), default=1)
    return max(_MIN_COLUMNS, min(_MAX_COLUMNS, (largest + 2) // 3 + 2))


def _note_cell(note: str, width: int) -> str:
    return (
        f'<mxCell id="detail_curation_note" value="{_xml_value(note)}" '
        'style="text;html=1;fontSize=10;fontColor=#6b7280;align=left;" vertex="1" parent="1">'
        f'<mxGeometry x="{_CANVAS_X}" y="{_CANVAS_Y - 26}" width="{width}" height="20" as="geometry"/>'
        "</mxCell>"
    )
