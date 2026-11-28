from __future__ import annotations

from typing import Any

from ..turn_tool_history import _build_tool_call
from .aws_overview_aggregation import _shape_large_overview_selection
from .aws_topology_cells import _node_refs
from .aws_topology_detail_candidates import (
    _rank_detail_candidates,
    _select_detail_candidate_graph,
    _substantial_detail_candidates,
    _topology_brief_parts,
    build_aws_topology_detail_candidates,
)
from .aws_topology_shapes import _matched_shape_lookup

_OMITTED_CANVAS_EDGE_TYPES = {"belongs_to_account"}


def build_aws_topology_diagram_tool_call(
    workflow_contract: dict[str, Any],
    topology_result: dict[str, Any],
    shape_library_result: dict[str, Any],
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    brief = topology_result.get("diagram_brief") if isinstance(topology_result, dict) else {}
    if not isinstance(brief, dict):
        return []
    selected_nodes = [node for node in (brief.get("selected_nodes") or []) if isinstance(node, dict)]
    selected_edges = [edge for edge in (brief.get("selected_edges") or []) if isinstance(edge, dict)]
    if not selected_nodes:
        return []
    selected_nodes, selected_edges, aggregation = _shape_large_overview_selection(selected_nodes, selected_edges, brief)
    rendered_edges = _renderable_edges(selected_edges)

    title = _diagram_title(workflow_contract)
    render_topology_result = dict(topology_result)
    if aggregation:
        render_topology_result["_overview_aggregation"] = aggregation
    xml = _render_aws_topology_xml(
        title=title,
        topology_result=render_topology_result,
        selected_nodes=selected_nodes,
        selected_edges=rendered_edges,
        shape_library_result=shape_library_result,
        omitted_edge_count=len(selected_edges) - len(rendered_edges),
    )
    if not xml.strip():
        return []
    return _build_tool_call("create_diagram", {"title": title, "xml": xml}, allowed_tool_names)


def build_aws_topology_detail_diagram_tool_calls(
    workflow_contract: dict[str, Any],
    topology_result: dict[str, Any],
    shape_library_result: dict[str, Any],
    allowed_tool_names: set[str] | None,
    *,
    max_diagrams: int = 3,
) -> list[dict[str, Any]]:
    candidates = _substantial_detail_candidates(
        _rank_detail_candidates(build_aws_topology_detail_candidates(topology_result))
    )[: max(0, max_diagrams)]
    selected_nodes, selected_edges, _brief = _topology_brief_parts(topology_result)
    if not selected_nodes:
        return []

    tool_calls: list[dict[str, Any]] = []

    # The complete "what runs on AWS" inventory always ships first: the
    # architecture overview aggregates high-cardinality services, this board
    # lists every resource type with its true account total.
    from .aws_diagram_quality_gate import apply_quality_gate
    from .aws_inventory_board import render_inventory_board_xml

    inventory_xml = render_inventory_board_xml(
        title="AWS Topology - Service inventory",
        topology_result=topology_result,
        selected_nodes=selected_nodes,
    )
    if inventory_xml.strip():
        tool_calls.extend(
            _build_tool_call(
                "create_diagram",
                {"title": "AWS Topology - Service inventory", "xml": apply_quality_gate(inventory_xml)},
                allowed_tool_names,
            )
        )
    for candidate in candidates:
        candidate_nodes, candidate_edges = _select_detail_candidate_graph(candidate, selected_nodes, selected_edges)
        rendered_edges = _renderable_edges(candidate_edges)
        if not candidate_nodes:
            continue
        title = f"AWS Topology Detail - {candidate['title']}"
        xml = _render_aws_topology_xml(
            title=title,
            topology_result=topology_result,
            selected_nodes=candidate_nodes,
            selected_edges=rendered_edges,
            shape_library_result=shape_library_result,
            omitted_edge_count=len(candidate_edges) - len(rendered_edges),
        )
        if not xml.strip():
            continue
        tool_calls.extend(_build_tool_call("create_diagram", {"title": title, "xml": xml}, allowed_tool_names))
    return tool_calls


def _diagram_title(workflow_contract: dict[str, Any]) -> str:
    topic = str(workflow_contract.get("topic") or "").strip()
    normalized_topic = topic.lower()
    if topic and normalized_topic not in {"aws", "topology", "diagram", "aws topology"}:
        return f"{topic} AWS Topology"
    return "AWS Topology Overview"


def _render_aws_topology_xml(
    *,
    title: str,
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    shape_library_result: dict[str, Any],
    omitted_edge_count: int = 0,
) -> str:
    shape_lookup = _matched_shape_lookup(shape_library_result)
    prefix = str(shape_library_result.get("prefix") or "mxgraph.aws4").strip() or "mxgraph.aws4"
    node_refs = _node_refs(selected_nodes)

    # Architecture-style container layout whenever a VPC is in the selection;
    # imported lazily because the structural module reuses helpers from here.
    from .aws_diagram_quality_gate import apply_quality_gate
    from .aws_topology_structural_layout import render_structural_topology_xml

    structural_xml = render_structural_topology_xml(
        title=title,
        topology_result=topology_result,
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        shape_lookup=shape_lookup,
        prefix=prefix,
        node_refs=node_refs,
    )
    if structural_xml is not None:
        return apply_quality_gate(structural_xml)

    # Selections without a VPC (the detail diagrams) use the curated banded
    # flow layout.
    from .aws_detail_layout import render_detail_topology_xml

    return apply_quality_gate(
        render_detail_topology_xml(
            title=title,
            topology_result=topology_result,
            selected_nodes=selected_nodes,
            selected_edges=selected_edges,
            shape_lookup=shape_lookup,
            prefix=prefix,
            omitted_edge_count=omitted_edge_count,
        )
    )


def _renderable_edges(selected_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        edge
        for edge in selected_edges
        if str(edge.get("type") or "").strip() not in _OMITTED_CANVAS_EDGE_TYPES
    ]

