"""VPC, regional-services and inter-VPC container blocks of the structural AWS overview."""

from __future__ import annotations

import math
from typing import Any

from .aws_cell_text import _xml_value
from .aws_structural_autolayout import stack_vpc_content
from .aws_structural_cells import _container_cell, _IconRenderer, _tier_label
from .aws_structural_styles import (
    _DEFAULT_FLOW_LAYER,
    _FLOW_LAYERS,
    _ICON_SLOT_H,
    _ICON_SLOT_W,
    _INTER_VPC_EDGE_LABELS,
    _INTER_VPC_EDGE_STYLE,
    _REGIONAL_STYLE,
    _SUBNET_GROUP_STYLE,
    _SUBNET_PAD,
    _SUBNET_TIER_STYLES,
    _SUBNET_TITLE_H,
    _TIER_ORDER,
    _VPC_PAD,
    _VPC_TITLE_H,
)


def _vpc_block(
    icon: _IconRenderer,
    vpc_ref: str,
    nodes_by_ref: dict[str, dict[str, Any]],
    tier_subnets: dict[str, list[str]],
    tier_children: dict[tuple[str, str], list[str]],
    subnet_tier: dict[str, str],
    vpc_level_refs: list[str],
) -> tuple[list[str], int, int]:
    ordered_subnets = _ordered_tier_subnets(vpc_ref, nodes_by_ref, tier_subnets, tier_children)
    ordered_vpc_level = sorted(
        vpc_level_refs, key=lambda ref: (str(nodes_by_ref[ref].get("type") or ""), ref)
    )

    # Deterministic vertical stack: one full-width band per tier in flow order,
    # gateways above and remaining VPC-level nodes below. This keeps the whole
    # VPC in a single column so the traffic-flow edges read top-to-bottom.
    layers = {
        ref: _FLOW_LAYERS.get(str(nodes_by_ref[ref].get("type") or ""), _DEFAULT_FLOW_LAYER)
        for ref in ordered_vpc_level
    }
    layout = stack_vpc_content(
        subnets=ordered_subnets,
        vpc_level=ordered_vpc_level,
        layers=layers,
        vpc_title_height=_VPC_TITLE_H,
        subnet_title_height=_SUBNET_TITLE_H,
        subnet_pad=_SUBNET_PAD,
    )

    node_rects: dict[str, tuple[int, int, int, int]] = layout["nodes"]
    cells = _subnet_tier_cells(icon, vpc_ref, nodes_by_ref, ordered_subnets, layout["subnets"], node_rects)
    for ref in ordered_vpc_level:
        rect = node_rects.get(ref)
        if rect is None:
            continue
        cells.append(icon.cell(nodes_by_ref[ref], ref, vpc_ref, rect[0] + _VPC_PAD, rect[1]))

    block_width = layout["width"] + 2 * _VPC_PAD
    block_height = layout["height"] + _VPC_PAD
    return cells, block_width, block_height


def _ordered_tier_subnets(
    vpc_ref: str,
    nodes_by_ref: dict[str, dict[str, Any]],
    tier_subnets: dict[str, list[str]],
    tier_children: dict[tuple[str, str], list[str]],
) -> list[dict[str, Any]]:
    # One container per subnet tier (not per subnet): real resources span all
    # AZs of a tier, so the tier is the meaningful boundary. Each tier lists its
    # AZs in the label and holds the resources placed in it.
    ordered_subnets: list[dict[str, Any]] = []
    for tier in _TIER_ORDER:
        subnet_refs = tier_subnets.get(tier) or []
        children = sorted(tier_children.get((vpc_ref, tier)) or [])
        if not subnet_refs and not children:
            continue
        azs = _tier_azs(nodes_by_ref, subnet_refs)
        ordered_subnets.append(
            {
                "ref": f"{vpc_ref}__tier_{tier}",
                "tier": tier,
                "children": children,
                "label": _tier_label(tier, len(subnet_refs), azs),
            }
        )
    return ordered_subnets


def _subnet_tier_cells(
    icon: _IconRenderer,
    vpc_ref: str,
    nodes_by_ref: dict[str, dict[str, Any]],
    ordered_subnets: list[dict[str, Any]],
    subnet_rects: dict[str, tuple[int, int, int, int]],
    node_rects: dict[str, tuple[int, int, int, int]],
) -> list[str]:
    cells: list[str] = []
    subnet_style = _SUBNET_GROUP_STYLE
    for subnet in ordered_subnets:
        rect = subnet_rects.get(subnet["ref"])
        if rect is None:
            continue
        x, y, width, height = rect
        fill, stroke, font = _SUBNET_TIER_STYLES[subnet["tier"]]
        cells.append(
            _container_cell(
                subnet["ref"],
                subnet["label"],
                subnet_style.format(fill=fill, stroke=stroke, font=font),
                x + _VPC_PAD,
                y,
                width,
                height,
                parent=vpc_ref,
            )
        )
        for child_ref in subnet["children"]:
            child_rect = node_rects.get(child_ref)
            if child_rect is None:
                continue
            cells.append(
                icon.cell(
                    nodes_by_ref[child_ref],
                    child_ref,
                    subnet["ref"],
                    child_rect[0] - x,
                    child_rect[1] - y,
                )
            )
    return cells


def _tier_azs(nodes_by_ref: dict[str, dict[str, Any]], subnet_refs: list[str]) -> list[str]:
    return sorted(
        {
            str(((nodes_by_ref[ref].get("attributes")) or {}).get("availability_zone") or "")
            .replace("eu-", "")
            .strip("-")
            for ref in subnet_refs
            if ref in nodes_by_ref
        }
        - {""}
    )


def _regional_box(
    icon: _IconRenderer,
    nodes_by_ref: dict[str, dict[str, Any]],
    refs: list[str],
    *,
    box_id: str,
    x: int,
    y: int,
    min_width: int,
    parent: str,
) -> tuple[list[str], int, int]:
    columns = max(3, min(8, math.ceil(math.sqrt(len(refs) * 2))))
    rows = math.ceil(len(refs) / columns)
    width = max(min_width, columns * _ICON_SLOT_W + 2 * _SUBNET_PAD)
    height = _SUBNET_TITLE_H + rows * _ICON_SLOT_H + _SUBNET_PAD
    cells = [
        _container_cell(box_id, "Regional services", _REGIONAL_STYLE, x, y, width, height, parent=parent)
    ]
    for index, ref in enumerate(refs):
        cells.append(
            icon.cell(
                nodes_by_ref[ref],
                ref,
                box_id,
                _SUBNET_PAD + (index % columns) * _ICON_SLOT_W,
                _SUBNET_TITLE_H + (index // columns) * _ICON_SLOT_H,
            )
        )
    return cells, width, height


def _inter_vpc_strip(
    icon: _IconRenderer,
    inter_vpc_refs: dict[str, list[str]],
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    *,
    x: int,
    y: int,
    min_width: int,
) -> tuple[list[str], int, int, list[str]]:
    refs = sorted(inter_vpc_refs)
    columns = max(3, min(8, len(refs)))
    rows = math.ceil(len(refs) / columns)
    width = max(min_width, columns * _ICON_SLOT_W + 2 * _SUBNET_PAD)
    height = _SUBNET_TITLE_H + rows * _ICON_SLOT_H + _SUBNET_PAD
    cells = [
        _container_cell(
            "inter_vpc_connectivity",
            "Inter-VPC connectivity",
            _REGIONAL_STYLE,
            x,
            y,
            width,
            height,
            parent="aws_cloud",
        )
    ]
    edge_cells: list[str] = []
    edge_index = 1
    for index, ref in enumerate(refs):
        cells.append(
            icon.cell(
                nodes_by_ref[ref],
                ref,
                "inter_vpc_connectivity",
                _SUBNET_PAD + (index % columns) * _ICON_SLOT_W,
                _SUBNET_TITLE_H + (index // columns) * _ICON_SLOT_H,
            )
        )
        label = _xml_value(_INTER_VPC_EDGE_LABELS.get(type_by_ref.get(ref, ""), "connects"))
        for vpc_ref in inter_vpc_refs[ref]:
            edge_cells.append(
                f'<mxCell id="ivc_{edge_index}" value="{label}" style="{_INTER_VPC_EDGE_STYLE}" '
                f'edge="1" parent="1" source="{ref}" target="{vpc_ref}">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>'
            )
            edge_index += 1
    return cells, width, height, edge_cells
