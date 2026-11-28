"""Deterministic grid placement of the structural AWS overview's VPC content and resource grids."""

from __future__ import annotations

from typing import Any

_SLOT_W_PX = 136
_SLOT_H_PX = 124


def wrap_grid(
    sizes: list[tuple[int, int]],
    *,
    max_width: int,
    gap_x: int = 14,
    gap_y: int = 12,
) -> tuple[list[tuple[int, int, int, int]], int, int]:
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
    gap_x, gap_y, band_gap = 16, 12, 20
    # Ingress nodes (gateways, load balancers) band above the tiers, data nodes (e.g. RDS) below.
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
    # All bands share one width, so the VPC reads as one column and the traffic-flow edges stay short.
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
