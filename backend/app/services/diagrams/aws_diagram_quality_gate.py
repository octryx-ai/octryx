"""Deterministic post-render quality gate for AWS diagrams.

Every rendered diagram is checked against measurable invariants before it is
delivered; violations never fail silently — they are stamped into the diagram
as a visible warning cell so the reader knows exactly what to distrust:

- sibling vertices must not overlap;
- children must fit inside their container;
- no container may hold more nodes than a reader can scan;
- edge density and canvas size must stay within readable bounds.

The gate measures the geometry the renderer actually produced (not what it
intended), so regressions in any layout path surface immediately.
"""

from __future__ import annotations

import itertools
import xml.etree.ElementTree as ET
from typing import Any

from ..error_facts import error_type

_MAX_CHILDREN_PER_CONTAINER = 40
_MAX_EDGES_PER_VERTEX = 3.0
_MAX_CANVAS_W = 6000
_MAX_CANVAS_H = 9000
_WARNING_CELL_ID = "quality_gate_warning"


def check_diagram_quality(xml: str) -> list[str]:
    """Return human-readable invariant violations; empty means the gate passed."""
    try:
        root = ET.fromstring(f"<mxGraphModel><root>{xml}</root></mxGraphModel>")
    except ET.ParseError as exc:
        line, column = exc.position
        return [f"diagram XML does not parse (error_type={error_type(exc)}, line={int(line)}, column={int(column)})"]

    vertices: list[tuple[str, str, float, float, float, float]] = []
    solid_vertices: list[tuple[str, str, float, float, float, float]] = []
    edge_count = 0
    for cell in root.iter("mxCell"):
        if cell.get("edge") == "1":
            edge_count += 1
            continue
        if cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        entry = (
            str(cell.get("id") or ""),
            str(cell.get("parent") or ""),
            float(geometry.get("x") or 0),
            float(geometry.get("y") or 0),
            float(geometry.get("width") or 0),
            float(geometry.get("height") or 0),
        )
        vertices.append(entry)
        if not _is_decorative_style(str(cell.get("style") or "")):
            solid_vertices.append(entry)

    violations: list[str] = []
    # Decorative overlays (sequence lifelines, invisible anchors, transparent
    # frames) overlap solid nodes BY DESIGN; only solid nodes must not.
    violations.extend(_check_sibling_overlap(solid_vertices))
    violations.extend(_check_children_fit(vertices))
    violations.extend(_check_container_occupancy(vertices))
    violations.extend(_check_density(vertices, edge_count))
    violations.extend(_check_canvas_size(vertices))
    return violations


def apply_quality_gate(xml: str) -> str:
    """Stamp violations into the diagram as a visible warning cell; a clean
    diagram passes through unchanged."""
    if not xml.strip():
        return xml
    violations = check_diagram_quality(xml)
    if not violations:
        return xml
    shown = violations[:3]
    more = len(violations) - len(shown)
    text = "QUALITY GATE: " + " | ".join(shown)
    if more > 0:
        text += f" | +{more} more"
    # The stamp owns its own row ABOVE the canvas (negative y): it must never
    # overlap the diagram title or any rendered node.
    warning = (
        f'<mxCell id="{_WARNING_CELL_ID}" value="{_escape(text)}" '
        'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fef2f2;strokeColor=#dc2626;'
        'fontSize=11;fontColor=#991b1b;align=left;verticalAlign=top;spacing=8;" '
        'vertex="1" parent="1">'
        '<mxGeometry x="60" y="-48" width="1480" height="36" as="geometry"/></mxCell>'
    )
    return warning + xml


def _is_decorative_style(style: str) -> bool:
    """Line/transparent overlay cells whose overlap with solid nodes is the
    intended rendering (UML lifelines, message anchors, sequence frames)."""
    return (
        "shape=line" in style
        or "fillOpacity=0" in style
        or "fillColor=none" in style
        or "shape=umlFrame" in style
    )


def _check_sibling_overlap(
    vertices: list[tuple[str, str, float, float, float, float]],
) -> list[str]:
    by_parent: dict[str, list[tuple[str, float, float, float, float]]] = {}
    for cell_id, parent, x, y, w, h in vertices:
        if cell_id == _WARNING_CELL_ID or w <= 0 or h <= 0:
            continue
        by_parent.setdefault(parent, []).append((cell_id, x, y, w, h))
    violations: list[str] = []
    for parent, siblings in by_parent.items():
        for a, b in itertools.combinations(siblings, 2):
            separated = (
                a[1] + a[3] <= b[1]
                or b[1] + b[3] <= a[1]
                or a[2] + a[4] <= b[2]
                or b[2] + b[4] <= a[2]
            )
            if not separated:
                violations.append(f"{a[0]} overlaps {b[0]} inside '{parent}'")
                break
        if len(violations) >= 3:
            break
    return violations


def _check_children_fit(
    vertices: list[tuple[str, str, float, float, float, float]],
) -> list[str]:
    bounds = {cell_id: (w, h) for cell_id, _parent, _x, _y, w, h in vertices}
    violations: list[str] = []
    for cell_id, parent, x, y, w, h in vertices:
        parent_bounds = bounds.get(parent)
        if parent_bounds is None:
            continue
        if x < 0 or y < 0 or x + w > parent_bounds[0] + 1 or y + h > parent_bounds[1] + 1:
            violations.append(f"{cell_id} exceeds the bounds of its container '{parent}'")
        if len(violations) >= 3:
            break
    return violations


def _check_container_occupancy(
    vertices: list[tuple[str, str, float, float, float, float]],
) -> list[str]:
    children: dict[str, int] = {}
    ids = {cell_id for cell_id, *_rest in vertices}
    for _cell_id, parent, *_rest in vertices:
        if parent in ids:
            children[parent] = children.get(parent, 0) + 1
    return [
        f"container '{parent}' holds {count} nodes (max {_MAX_CHILDREN_PER_CONTAINER})"
        for parent, count in sorted(children.items())
        if count > _MAX_CHILDREN_PER_CONTAINER
    ]


def _check_density(
    vertices: list[tuple[str, str, float, float, float, float]], edge_count: int
) -> list[str]:
    vertex_count = max(1, len(vertices))
    ratio = edge_count / vertex_count
    if ratio > _MAX_EDGES_PER_VERTEX:
        return [
            f"edge density {ratio:.1f} edges/node exceeds {_MAX_EDGES_PER_VERTEX:.0f} - unreadable wiring"
        ]
    return []


def _check_canvas_size(
    vertices: list[tuple[str, str, float, float, float, float]],
) -> list[str]:
    top_level = [item for item in vertices if item[1] in {"", "1"}]
    max_x = max((x + w for _i, _p, x, _y, w, _h in top_level), default=0)
    max_y = max((y + h for _i, _p, _x, y, _w, h in top_level), default=0)
    if max_x > _MAX_CANVAS_W or max_y > _MAX_CANVAS_H:
        return [f"canvas {max_x:.0f}x{max_y:.0f} exceeds {_MAX_CANVAS_W}x{_MAX_CANVAS_H}"]
    return []


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
