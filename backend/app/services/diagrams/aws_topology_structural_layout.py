"""Structural (container-based) layout for AWS topology overview diagrams."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _safe_cell_id, _xml_value
from .aws_structural_blocks import _inter_vpc_strip, _regional_box, _vpc_block
from .aws_structural_cells import (
    _cloud_label,
    _container_cell,
    _IconRenderer,
    _relationship_cells,
    _structural_legend,
    _vpc_label,
)
from .aws_structural_placement import StructuralPlacement, build_structural_placement
from .aws_structural_styles import (
    _AWS_CLOUD_STYLE,
    _CANVAS_X,
    _CANVAS_Y,
    _CLOUD_PAD,
    _CLOUD_TITLE_H,
    _REGION_PAD,
    _REGION_STYLE,
    _REGION_TITLE_H,
    _VPC_STYLE,
)
from .aws_topology_cells import _title_cell


def render_structural_topology_xml(
    *,
    title: str,
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    shape_lookup: dict[str, str],
    prefix: str,
    node_refs: dict[int, str],
) -> str | None:
    placement = build_structural_placement(selected_nodes, selected_edges, node_refs)
    if placement is None:
        return None

    icon = _IconRenderer(shape_lookup, prefix)
    vpc_cells, cursor_y, inner_width = _cloud_content_cells(placement, icon)

    inter_vpc_edge_cells: list[str] = []
    if placement.inter_vpc_refs:
        strip_cells, strip_width, strip_height, inter_vpc_edge_cells = _inter_vpc_strip(
            icon,
            placement.inter_vpc_refs,
            placement.nodes_by_ref,
            placement.type_by_ref,
            x=_CLOUD_PAD,
            y=cursor_y,
            min_width=inner_width,
        )
        vpc_cells.extend(strip_cells)
        cursor_y += strip_height + 24
        inner_width = max(inner_width, strip_width)

    cloud_width = inner_width + 2 * _CLOUD_PAD
    cloud_height = cursor_y + _CLOUD_PAD
    cells: list[str] = [
        _title_cell(title, topology_result),
        _structural_legend(
            topology_result, selected_nodes, selected_edges, len(placement.excluded), placement.curation_notes
        ),
        _container_cell(
            "aws_cloud",
            _cloud_label(topology_result),
            _AWS_CLOUD_STYLE,
            _CANVAS_X,
            _CANVAS_Y,
            cloud_width,
            cloud_height,
            parent="1",
        ),
    ]
    cells.extend(vpc_cells)
    cells.extend(
        _relationship_cells(
            selected_edges, placement.nodes_by_ref, placement.type_by_ref, placement.excluded, placement.endpoint
        )
    )
    cells.extend(inter_vpc_edge_cells)
    return "".join(cells)


def _cloud_content_cells(placement: StructuralPlacement, icon: _IconRenderer) -> tuple[list[str], int, int]:
    nodes_by_ref = placement.nodes_by_ref
    region_of_vpc = {
        ref: str(nodes_by_ref[ref].get("region") or "").strip() for ref in placement.vpc_refs
    }
    regions = sorted({value for value in region_of_vpc.values() if value})
    if len(regions) > 1:
        return _multi_region_cells(placement, icon, region_of_vpc, regions)
    return _single_region_cells(placement, icon)


def _vpc_with_container(
    placement: StructuralPlacement,
    icon: _IconRenderer,
    vpc_ref: str,
    x: int,
    y: int,
    parent: str,
) -> tuple[list[str], int, int]:
    block_cells, width, height = _vpc_block(
        icon,
        vpc_ref,
        placement.nodes_by_ref,
        placement.tier_of_vpc.get(vpc_ref, {}),
        placement.tier_children,
        placement.subnet_tier,
        placement.vpc_children[vpc_ref],
    )
    container = _container_cell(
        vpc_ref,
        _vpc_label(placement.nodes_by_ref[vpc_ref]),
        _VPC_STYLE,
        x,
        y,
        width,
        height,
        parent=parent,
    )
    return [container, *block_cells], width, height


def _single_region_cells(placement: StructuralPlacement, icon: _IconRenderer) -> tuple[list[str], int, int]:
    vpc_cells: list[str] = []
    cursor_y = _CLOUD_TITLE_H
    inner_width = 0
    for vpc_ref in sorted(placement.vpc_refs):
        vpc_group, width, height = _vpc_with_container(
            placement, icon, vpc_ref, _CLOUD_PAD, cursor_y, "aws_cloud"
        )
        vpc_cells.extend(vpc_group)
        cursor_y += height + 24
        inner_width = max(inner_width, width)

    if placement.regional:
        box_cells, box_width, box_height = _regional_box(
            icon,
            placement.nodes_by_ref,
            sorted(placement.regional, key=lambda ref: placement.type_by_ref[ref]),
            box_id="regional_services",
            x=_CLOUD_PAD,
            y=cursor_y,
            min_width=inner_width,
            parent="aws_cloud",
        )
        vpc_cells.extend(box_cells)
        cursor_y += box_height + 24
        inner_width = max(inner_width, box_width)
    return vpc_cells, cursor_y, inner_width


def _multi_region_cells(
    placement: StructuralPlacement,
    icon: _IconRenderer,
    region_of_vpc: dict[str, str],
    regions: list[str],
) -> tuple[list[str], int, int]:
    # AWS Cloud -> one dashed region frame per region -> that region's VPCs
    # and regional services. Nodes without region metadata stay with the
    # primary region.
    primary_region = regions[0] if regions else ""
    vpc_cells: list[str] = []
    cursor_y = _CLOUD_TITLE_H
    inner_width = 0
    for region_name in regions:
        region_id = f"region_{_safe_cell_id(region_name, fallback='region')}"
        region_cells, region_width, region_height = _region_frame_content(
            placement, icon, region_name, region_id, region_of_vpc, regions, primary_region
        )
        vpc_cells.append(
            _container_cell(
                region_id,
                _xml_value(region_name),
                _REGION_STYLE,
                _CLOUD_PAD,
                cursor_y,
                region_width + 2 * _REGION_PAD,
                region_height,
                parent="aws_cloud",
            )
        )
        vpc_cells.extend(region_cells)
        cursor_y += region_height + 24
        inner_width = max(inner_width, region_width + 2 * _REGION_PAD)
    return vpc_cells, cursor_y, inner_width


def _region_frame_content(
    placement: StructuralPlacement,
    icon: _IconRenderer,
    region_name: str,
    region_id: str,
    region_of_vpc: dict[str, str],
    regions: list[str],
    primary_region: str,
) -> tuple[list[str], int, int]:
    nodes_by_ref = placement.nodes_by_ref

    def _node_region(ref: str) -> str:
        value = str(nodes_by_ref[ref].get("region") or "").strip()
        return value if value in regions else primary_region

    region_cells: list[str] = []
    inner_cursor = _REGION_TITLE_H
    region_width = 0
    for vpc_ref in sorted(ref for ref in placement.vpc_refs if (region_of_vpc[ref] or primary_region) == region_name):
        vpc_group, width, height = _vpc_with_container(placement, icon, vpc_ref, _REGION_PAD, inner_cursor, region_id)
        region_cells.extend(vpc_group)
        inner_cursor += height + 24
        region_width = max(region_width, width)
    region_regional = sorted(
        (ref for ref in placement.regional if _node_region(ref) == region_name),
        key=lambda ref: placement.type_by_ref[ref],
    )
    if region_regional:
        box_cells, box_width, box_height = _regional_box(
            icon,
            nodes_by_ref,
            region_regional,
            box_id=f"regional_services_{_safe_cell_id(region_name, fallback='region')}",
            x=_REGION_PAD,
            y=inner_cursor,
            min_width=region_width,
            parent=region_id,
        )
        region_cells.extend(box_cells)
        inner_cursor += box_height + 24
        region_width = max(region_width, box_width)
    region_height = inner_cursor + _REGION_PAD - 24
    return region_cells, region_width, region_height
