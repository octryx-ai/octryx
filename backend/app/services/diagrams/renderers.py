"""Drawio XML rendering of the diagram intermediate representation."""

from __future__ import annotations

import html

from .diagram_styles import edge_style as default_edge_style
from .models import DiagramIR


def cell_xml(
    cell_id: str, value: str, style: str, x: int, y: int, width: int, height: int, *, parent: str = "1"
) -> str:
    return (
        f'<mxCell id="{cell_id}" value="{html.escape(value)}" style="{style}" vertex="1" parent="{parent}">'
        f'<mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry"/></mxCell>'
    )


def edge_xml(
    edge_id: str,
    source: str,
    target: str,
    *,
    label: str = "",
    points: list[tuple[int, int]] | None = None,
    style: str | None = None,
    parent: str = "1",
    label_position: float | None = None,
) -> str:
    geometry = '<mxGeometry relative="1" as="geometry"/>'
    if points:
        point_xml = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
        geometry = f'<mxGeometry relative="1" as="geometry"><Array as="points">{point_xml}</Array></mxGeometry>'
    edge_style = style or default_edge_style()
    edge = (
        f'<mxCell id="{edge_id}" style="{edge_style}" edge="1" parent="{parent}" source="{source}" '
        f'target="{target}">{geometry}</mxCell>'
    )
    if not label:
        return edge
    position = -0.1 if label_position is None else max(-1.0, min(1.0, float(label_position)))
    label_xml = (
        f'<mxCell id="{edge_id}_label" value="{html.escape(label)}" '
        'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];fontSize=11;'
        'fillColor=#ffffff;" '
        f'vertex="1" connectable="0" parent="{edge_id}"><mxGeometry x="{position}" y="1" relative="1" '
        'as="geometry"><mxPoint x="0" y="-10" as="offset"/></mxGeometry></mxCell>'
    )
    return edge + label_xml


def render_diagram_ir(diagram: DiagramIR) -> str:
    """The drawio XML (bare ``mxCell`` elements) of a node-link diagram."""
    cells = [
        cell_xml(
            "title",
            diagram.title,
            "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;fontStyle=1;",
            220,
            10,
            420,
            30,
        )
    ]
    for node in diagram.nodes:
        cells.append(
            cell_xml(node.id, node.label, node.style, node.x, node.y, node.width, node.height, parent=node.parent)
        )
    for edge in diagram.edges:
        style = edge.style or default_edge_style()
        cells.append(
            edge_xml(
                edge.id,
                edge.source,
                edge.target,
                label=edge.label,
                points=list(edge.points) or None,
                style=style,
                parent=edge.parent,
                label_position=edge.label_position,
            )
        )
    return "".join(cells)
