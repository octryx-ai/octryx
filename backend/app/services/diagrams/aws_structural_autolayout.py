"""Graphviz-based auto layout for the structural AWS overview.

Lays out the content of one VPC container with the ``dot`` hierarchical
engine: subnets become nested clusters, resources become fixed-size nodes,
and the kept relationship edges drive placement so related resources sit
next to each other and edges flow top-down with minimal crossings.

Only geometry comes from graphviz — the draw.io XML (styles, containers,
edges) is still emitted by ``aws_topology_structural_layout``. When the
``dot`` binary is unavailable or fails, the caller falls back to the
deterministic grid layout, so graphviz is an optional quality upgrade,
not a hard dependency.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from typing import Any

_SLOT_W_PX = 136
_SLOT_H_PX = 124
_POINTS_PER_INCH = 72.0
# Generous: the very first dot invocation on a host can spend ~15s building
# its font cache; afterwards a layout takes well under a second.
_DOT_TIMEOUT_SECONDS = 25
# The backend process does not necessarily have Homebrew on PATH.
_DOT_CANDIDATES = ("dot", "/opt/homebrew/bin/dot", "/usr/local/bin/dot", "/usr/bin/dot")
_PLACEHOLDER_PREFIX = "__ph_"


def dot_binary() -> str | None:
    for candidate in _DOT_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def layout_vpc_content(
    *,
    subnets: list[dict[str, Any]],
    vpc_level: list[str],
    edges: list[tuple[str, str]],
    vpc_title_height: int,
    layers: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """Compute rects for one VPC's content.

    ``subnets``: ``[{"ref": str, "tier": str, "children": [refs]}]`` in the
    desired tier order. ``layers`` pins cluster-free nodes to traffic-flow
    ranks (0 = top). Returns ``{"width", "height", "subnets": {ref: rect},
    "nodes": {ref: rect}}`` with slot rects relative to the VPC container
    origin (title offset already applied), or ``None`` when graphviz is not
    available or the layout fails.
    """
    binary = dot_binary()
    if binary is None:
        return None
    dot_source = _build_dot(subnets, vpc_level, edges, layers or {})
    try:
        completed = subprocess.run(
            [binary, "-Tjson"],
            input=dot_source.encode("utf-8"),
            capture_output=True,
            timeout=_DOT_TIMEOUT_SECONDS,
            check=True,
        )
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return _parse_layout(payload, vpc_title_height)


def _build_dot(
    subnets: list[dict[str, Any]],
    vpc_level: list[str],
    edges: list[tuple[str, str]],
    layers: dict[str, int],
) -> str:
    slot_w_in = _SLOT_W_PX / _POINTS_PER_INCH
    slot_h_in = _SLOT_H_PX / _POINTS_PER_INCH
    lines = [
        "digraph aws_vpc {",
        '  graph [rankdir=TB, ranksep="0.55", nodesep="0.35", compound=true];',
        f'  node [shape=box, fixedsize=true, label="", width={slot_w_in:.3f}, height={slot_h_in:.3f}];',
        "  edge [arrowsize=0.6];",
    ]
    tier_anchors: list[str] = []
    for subnet in subnets:
        ref = str(subnet["ref"])
        children = [str(child) for child in subnet.get("children") or []]
        lines.append(f"  subgraph {_quote('cluster_' + ref)} {{")
        # The label text is never rendered; it only reserves the vertical space
        # the draw.io container title will occupy.
        lines.append('    graph [margin=14, label="title", fontsize=22];')
        if children:
            lines.extend(f"    {_quote(child)};" for child in children)
        else:
            placeholder = _PLACEHOLDER_PREFIX + ref
            lines.append(
                f"    {_quote(placeholder)} [style=invis, width=2.5, height=0.35];"
            )
        lines.append("  }")
        anchor = children[0] if children else _PLACEHOLDER_PREFIX + ref
        if not tier_anchors or _tier_of(subnets, tier_anchors[-1]) != subnet.get("tier"):
            tier_anchors.append(anchor)
    lines.extend(f"  {_quote(ref)};" for ref in vpc_level)

    # Traffic-flow ranks: one invisible anchor per layer, chained top-down;
    # cluster-free nodes are pinned to their layer's rank. Rank constraints
    # do not work across cluster boundaries, so cluster children stay free.
    clustered = {str(child) for subnet in subnets for child in subnet.get("children") or []}
    rankable_layers = sorted({layer for ref, layer in layers.items() if ref not in clustered})
    if len(rankable_layers) > 1:
        for layer in rankable_layers:
            lines.append(
                f'  {_quote(_layer_anchor(layer))} [style=invis, fixedsize=true, width=0.02, height=0.02];'
            )
        for upper, lower in zip(rankable_layers, rankable_layers[1:]):
            lines.append(
                f"  {_quote(_layer_anchor(upper))} -> {_quote(_layer_anchor(lower))} [style=invis];"
            )
        for layer in rankable_layers:
            members = sorted(
                ref for ref, ref_layer in layers.items() if ref_layer == layer and ref not in clustered
            )
            group = "; ".join(_quote(ref) for ref in [_layer_anchor(layer), *members])
            lines.append(f"  {{ rank=same; {group}; }}")

    for source, target in edges:
        source_layer, target_layer = layers.get(source), layers.get(target)
        if source in clustered or target in clustered or source_layer is None or target_layer is None:
            lines.append(f"  {_quote(source)} -> {_quote(target)};")
        elif source_layer > target_layer:
            # The evidence direction contradicts the flow layers (for example
            # route_table -> internet_gateway); reverse it for ranking only.
            lines.append(f"  {_quote(target)} -> {_quote(source)} [dir=back];")
        elif source_layer == target_layer:
            lines.append(f"  {_quote(source)} -> {_quote(target)} [constraint=false];")
        else:
            lines.append(f"  {_quote(source)} -> {_quote(target)};")

    # Invisible chain keeps the tier order (public above private) when the
    # relationship edges alone do not enforce it.
    for first, second in zip(tier_anchors, tier_anchors[1:]):
        lines.append(f"  {_quote(first)} -> {_quote(second)} [style=invis];")
    lines.append("}")
    return "\n".join(lines)


def _layer_anchor(layer: int) -> str:
    return f"{_PLACEHOLDER_PREFIX}layer_{layer}"


def _tier_of(subnets: list[dict[str, Any]], anchor: str) -> str:
    for subnet in subnets:
        ref = str(subnet["ref"])
        children = [str(child) for child in subnet.get("children") or []]
        if anchor == _PLACEHOLDER_PREFIX + ref or anchor in children:
            return str(subnet.get("tier") or "")
    return ""


def _parse_layout(payload: dict[str, Any], vpc_title_height: int) -> dict[str, Any] | None:
    graph_bb = _parse_bb(payload.get("bb"))
    if graph_bb is None:
        return None
    _, _, graph_right, graph_top = graph_bb
    subnet_rects: dict[str, tuple[int, int, int, int]] = {}
    node_rects: dict[str, tuple[int, int, int, int]] = {}
    for obj in payload.get("objects") or []:
        name = str(obj.get("name") or "")
        if name.startswith("cluster_"):
            bb = _parse_bb(obj.get("bb"))
            if bb is None:
                continue
            x0, y0, x1, y1 = bb
            subnet_rects[name[len("cluster_") :]] = (
                round(x0),
                round(graph_top - y1) + vpc_title_height,
                round(x1 - x0),
                round(y1 - y0),
            )
        elif "pos" in obj and not name.startswith(_PLACEHOLDER_PREFIX):
            rect = _node_rect(obj, graph_top, vpc_title_height)
            if rect is not None:
                node_rects[name] = rect
    if not node_rects and not subnet_rects:
        return None
    return {
        "width": round(graph_right),
        "height": round(graph_top) + vpc_title_height,
        "subnets": subnet_rects,
        "nodes": node_rects,
    }


def _node_rect(
    obj: dict[str, Any], graph_top: float, vpc_title_height: int
) -> tuple[int, int, int, int] | None:
    try:
        center_x, center_y = (float(part) for part in str(obj["pos"]).split(","))
        width = float(obj.get("width") or 0) * _POINTS_PER_INCH
        height = float(obj.get("height") or 0) * _POINTS_PER_INCH
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (
        round(center_x - width / 2),
        round(graph_top - center_y - height / 2) + vpc_title_height,
        round(width),
        round(height),
    )


def wrap_grid(
    sizes: list[tuple[int, int]],
    *,
    max_width: int,
    gap_x: int = 14,
    gap_y: int = 12,
) -> tuple[list[tuple[int, int, int, int]], int, int]:
    """Left-to-right wrap layout; returns (rects, total_width, total_height)."""
    rects: list[tuple[int, int, int, int]] = []
    cursor_x = 0
    cursor_y = 0
    row_height = 0
    total_width = 0
    for width, height in sizes:
        if cursor_x + width > max_width and cursor_x > 0:
            cursor_y += row_height + gap_y
            cursor_x = 0
            row_height = 0
        rects.append((cursor_x, cursor_y, width, height))
        cursor_x += width + gap_x
        row_height = max(row_height, height)
        total_width = max(total_width, cursor_x - gap_x)
    total_height = cursor_y + row_height if rects else 0
    return rects, total_width, total_height


def stack_vpc_content(
    *,
    subnets: list[dict[str, Any]],
    vpc_level: list[str],
    layers: dict[str, int],
    vpc_title_height: int,
    subnet_title_height: int,
    subnet_pad: int,
) -> dict[str, Any]:
    """Deterministic top-down band layout for one VPC's content.

    Every tier becomes one full-width band, stacked in the given order. The
    ``vpc_level`` nodes are split by flow layer: ingress ones (layer <= 1, e.g.
    gateways and load balancers) form a band above the tiers, data ones
    (layer >= 2, e.g. RDS) a band below, each ordered by layer. All bands share
    one width, so the whole VPC reads as a single vertical column and the
    traffic-flow edges stay short and top-to-bottom. Unlike the dot layout this
    never places tiers side by side or floats gateways off to one edge.

    Same result shape as :func:`layout_vpc_content`.
    """
    gap_x, gap_y, band_gap = 16, 12, 20
    ingress_refs = sorted(
        (ref for ref in vpc_level if layers.get(ref, 2) <= 1),
        key=lambda ref: (layers.get(ref, 2), ref),
    )
    data_refs = sorted(
        (ref for ref in vpc_level if layers.get(ref, 2) >= 2),
        key=lambda ref: (layers.get(ref, 2), ref),
    )

    counts = [len(subnet.get("children") or []) for subnet in subnets]
    counts += [len(ingress_refs), len(data_refs)]
    columns = max(1, min(6, max(counts) if counts else 1))
    inner_width = columns * _SLOT_W_PX + (columns - 1) * gap_x
    container_width = inner_width + 2 * subnet_pad

    subnet_rects: dict[str, tuple[int, int, int, int]] = {}
    node_rects: dict[str, tuple[int, int, int, int]] = {}
    cursor_y = vpc_title_height

    def _place_strip(refs: list[str]) -> None:
        nonlocal cursor_y
        if not refs:
            return
        rects, _, strip_h = wrap_grid(
            [(_SLOT_W_PX, _SLOT_H_PX)] * len(refs),
            max_width=inner_width,
            gap_x=gap_x,
            gap_y=gap_y,
        )
        for ref, (rx, ry, rw, rh) in zip(refs, rects):
            node_rects[ref] = (subnet_pad + rx, cursor_y + ry, rw, rh)
        cursor_y += strip_h + band_gap

    _place_strip(ingress_refs)
    for subnet in subnets:
        children = [str(child) for child in subnet.get("children") or []]
        if children:
            child_rects, _, inner_h = wrap_grid(
                [(_SLOT_W_PX, _SLOT_H_PX)] * len(children),
                max_width=inner_width,
                gap_x=gap_x,
                gap_y=gap_y,
            )
            band_h = subnet_title_height + inner_h + subnet_pad
        else:
            child_rects, band_h = [], subnet_title_height + 12
        subnet_rects[str(subnet["ref"])] = (0, cursor_y, container_width, band_h)
        for child, (rx, ry, rw, rh) in zip(children, child_rects):
            node_rects[child] = (
                subnet_pad + rx,
                cursor_y + subnet_title_height + ry,
                rw,
                rh,
            )
        cursor_y += band_h + band_gap
    _place_strip(data_refs)

    height = cursor_y - band_gap if node_rects or subnet_rects else cursor_y
    return {
        "width": container_width,
        "height": height,
        "subnets": subnet_rects,
        "nodes": node_rects,
    }


def grid_vpc_content(
    *,
    subnets: list[dict[str, Any]],
    vpc_level: list[str],
    vpc_title_height: int,
    subnet_title_height: int,
    subnet_pad: int,
) -> dict[str, Any]:
    """Deterministic grid fallback with the same result shape as
    :func:`layout_vpc_content`, used when graphviz is unavailable."""
    subnet_rects: dict[str, tuple[int, int, int, int]] = {}
    node_rects: dict[str, tuple[int, int, int, int]] = {}
    cursor_y = vpc_title_height
    block_width = 3 * _SLOT_W_PX + 2 * subnet_pad
    current_tier = None
    cursor_x = 0
    row_height = 0
    for subnet in subnets:
        if subnet.get("tier") != current_tier:
            if current_tier is not None:
                cursor_y += row_height + 16
            current_tier = subnet.get("tier")
            cursor_x = 0
            row_height = 0
        children = [str(child) for child in subnet.get("children") or []]
        columns = max(1, min(3, len(children)))
        rows = max(1, math.ceil(len(children) / columns)) if children else 0
        width = max(200, columns * _SLOT_W_PX + 2 * subnet_pad)
        height = subnet_title_height + rows * _SLOT_H_PX + (subnet_pad if children else 10)
        if cursor_x + width > 1500 and cursor_x > 0:
            cursor_y += row_height + 16
            cursor_x = 0
            row_height = 0
        subnet_rects[str(subnet["ref"])] = (cursor_x, cursor_y, width, height)
        for index, child in enumerate(children):
            node_rects[child] = (
                cursor_x + subnet_pad + (index % columns) * _SLOT_W_PX,
                cursor_y + subnet_title_height + (index // columns) * _SLOT_H_PX,
                _SLOT_W_PX,
                _SLOT_H_PX,
            )
        cursor_x += width + 16
        row_height = max(row_height, height)
        block_width = max(block_width, cursor_x - 16)
    if current_tier is not None:
        cursor_y += row_height + 16

    if vpc_level:
        columns = max(3, min(8, math.ceil(math.sqrt(len(vpc_level) * 2))))
        for index, ref in enumerate(vpc_level):
            node_rects[ref] = (
                (index % columns) * _SLOT_W_PX,
                cursor_y + (index // columns) * _SLOT_H_PX,
                _SLOT_W_PX,
                _SLOT_H_PX,
            )
        cursor_y += math.ceil(len(vpc_level) / columns) * _SLOT_H_PX
        block_width = max(block_width, columns * _SLOT_W_PX)

    return {
        "width": block_width,
        "height": cursor_y,
        "subnets": subnet_rects,
        "nodes": node_rects,
    }


def _parse_bb(value: Any) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = (float(part) for part in str(value).split(","))
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _quote(name: str) -> str:
    return '"' + name.replace('"', "") + '"'
