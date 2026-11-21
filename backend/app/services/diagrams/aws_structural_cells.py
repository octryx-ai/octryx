"""Icon, container, label and legend cells for the structural AWS overview layout."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _truncate_label, _xml_value
from .aws_diagram_naming import display_name
from .aws_structural_placement import _iter_kept_edges
from .aws_structural_styles import (
    _ICON_LABEL_WIDTH,
    _ICON_SIZE,
    _ICON_SLOT_W,
    _LABEL_MAX,
    _SUBTITLE_MAX,
    _TIER_LABELS,
)
from .aws_topology_cells import _coverage_gap_note, _node_value
from .aws_topology_edges import _edge_style, _edge_value
from .aws_topology_shapes import _DEFAULT_ICON_FILL, _NODE_TYPE_ICON_FILLS, _node_shape


class _IconRenderer:
    def __init__(self, shape_lookup: dict[str, str], prefix: str) -> None:
        self._shape_lookup = shape_lookup
        self._prefix = prefix

    def cell(self, node: dict[str, Any], cell_id: str, parent_id: str, x: int, y: int) -> str:
        node_type = str(node.get("type") or "resource")
        label = display_name(node) or node_type or cell_id
        value = _node_value(
            label, node_type, node, label_max=_LABEL_MAX, subtitle_max=_SUBTITLE_MAX
        )
        shape = _node_shape(node_type, self._shape_lookup)
        icon_x = x + (_ICON_SLOT_W - _ICON_SIZE) // 2
        if shape:
            fill = _NODE_TYPE_ICON_FILLS.get(node_type, _DEFAULT_ICON_FILL)
            style = (
                f"shape={self._prefix}.resourceIcon;resIcon={self._prefix}.{shape};"
                "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                f"fontSize=10;fontColor=#111827;aspect=fixed;fillColor={fill};"
                f"strokeColor=#ffffff;whiteSpace=wrap;labelWidth={_ICON_LABEL_WIDTH};"
            )
            return (
                f'<mxCell id="{cell_id}" value="{value}" style="{style}" vertex="1" parent="{parent_id}">'
                f'<mxGeometry x="{icon_x}" y="{y}" width="{_ICON_SIZE}" height="{_ICON_SIZE}" as="geometry"/></mxCell>'
            )
        style = (
            "rounded=1;whiteSpace=wrap;html=1;fontSize=10;align=center;verticalAlign=middle;"
            "fillColor=#f8fafc;strokeColor=#94a3b8;fontColor=#111827;"
        )
        return (
            f'<mxCell id="{cell_id}" value="{value}" style="{style}" vertex="1" parent="{parent_id}">'
            f'<mxGeometry x="{x + 4}" y="{y}" width="{_ICON_SLOT_W - 8}" height="{_ICON_SIZE}" as="geometry"/></mxCell>'
        )


def _tier_label(tier: str, subnet_count: int, azs: list[str]) -> str:
    name = _TIER_LABELS.get(tier, "Subnets")
    if subnet_count:
        name = f"{name} ({subnet_count})"
    if azs:
        name = f"{name} | {', '.join(azs)}"
    return _xml_value(_truncate_label(name, 60))


def _relationship_cells(
    selected_edges: list[dict[str, Any]],
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    excluded: set[str],
    endpoint: Any,
) -> list[str]:
    cells: list[str] = []
    for edge_index, (source, target, edge_type, edge) in enumerate(
        _iter_kept_edges(selected_edges, endpoint, type_by_ref, nodes_by_ref, excluded), start=1
    ):
        value = _edge_value(edge_type, edge)
        cells.append(
            f'<mxCell id="srel_{edge_index}" value="{value}" '
            f'style="{_edge_style(edge_type)}" edge="1" parent="1" source="{source}" target="{target}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    return cells


def _container_cell(
    cell_id: str,
    label: str,
    style: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    parent: str,
) -> str:
    return (
        f'<mxCell id="{cell_id}" value="{label}" style="{style}" vertex="1" parent="{parent}">'
        f'<mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry"/></mxCell>'
    )


def _cloud_label(topology_result: dict[str, Any]) -> str:
    account = str(topology_result.get("account_id") or "").strip()
    region = str(topology_result.get("region") or "").strip()
    parts = ["AWS Cloud"]
    if account:
        parts.append(account)
    if region:
        parts.append(region)
    return " | ".join(parts)


def _vpc_label(node: dict[str, Any]) -> str:
    label = str(node.get("label") or "VPC").strip()
    attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    cidr = str((attrs or {}).get("cidr_block") or "").strip()
    text = f"VPC {label}" if not label.lower().startswith("vpc") else label
    if cidr:
        text = f"{text} ({cidr})"
    return _xml_value(_truncate_label(text, 70))


def _structural_legend(
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    excluded_count: int,
    curation_notes: list[str],
) -> str:
    value = (
        "Evidence-backed AWS architecture from aws_topology_snapshot. VPC, subnet, and regional "
        "placement is shown by nesting instead of membership edges. "
        f"Selected nodes: {len(selected_nodes)}; relationships in evidence: {len(selected_edges)}."
    )
    if curation_notes:
        value += " " + "; ".join(curation_notes) + "."
    if excluded_count:
        value += (
            f" {excluded_count} security-group/CIDR nodes are omitted here; "
            "see the security detail diagram for traffic rules."
        )
    coverage_gap = _coverage_gap_note(topology_result)
    if coverage_gap:
        value += f" {coverage_gap}"
    return (
        f'<mxCell id="topology_legend" value="{_xml_value(value)}" '
        'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#cbd5e1;'
        'fontSize=12;fontColor=#334155;align=left;verticalAlign=top;spacing=10;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="92" width="1480" height="64" as="geometry"/></mxCell>'
    )
