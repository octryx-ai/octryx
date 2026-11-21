"""Service-inventory board + substance-based detail selection."""

import json

from app.services.diagrams.aws_inventory_board import build_inventory_cards
from app.services.diagrams.aws_topology_diagram import (
    build_aws_topology_detail_diagram_tool_calls,
)
from tests.aws_topology_structural_layout_support import _contract, _shape_library
from tests.test_aws_detail_layout import _planned_by_title, _security_topology


def _titles(planned):
    return [json.loads(call["function"]["arguments"])["title"] for call in planned]


def test_inventory_cards_use_true_totals_not_brief_selection():
    topology = _security_topology()
    topology["service_summary"] = dict(topology["service_summary"] or {})
    # full snapshot knows 25 queues; the brief only selected a few nodes
    topology["service_summary"]["node_counts_by_type"] = {
        "sqs_queue": 25,
        "load_balancer": 1,
        "security_group": 3,  # structural -> excluded from the inventory
    }
    cards = build_inventory_cards(topology, topology["diagram_brief"]["selected_nodes"])
    by_type = {card["type"]: card for card in cards}
    assert by_type["sqs_queue"]["count"] == 25
    assert "security_group" not in by_type
    assert by_type["load_balancer"]["names"] == ["app-alb"]


def test_inventory_board_ships_first_and_details_need_substance():
    planned = build_aws_topology_detail_diagram_tool_calls(
        _contract(), _security_topology(), _shape_library(), {"create_diagram"}
    )
    titles = _titles(planned)
    assert titles[0] == "AWS Topology - Service inventory"
    # the security candidate has substance (7 nodes) and renders
    assert any("Security group" in title for title in titles)
    inventory_xml = _planned_by_title(planned, "Service inventory")["xml"]
    assert "Complete service inventory" in inventory_xml
    assert "quality_gate_warning" not in inventory_xml


def test_thin_candidates_render_no_detail_diagram():
    topology = _security_topology()
    brief = topology["diagram_brief"]
    # shrink the evidence below the substance thresholds: 2 nodes, 1 edge
    brief["selected_nodes"] = [
        node for node in brief["selected_nodes"] if node["ref"] in {"sg_db", "rds1"}
    ]
    brief["selected_edges"] = [
        edge for edge in brief["selected_edges"]
        if edge["source_ref"] == "rds1" and edge["target_ref"] == "sg_db"
    ]
    topology["service_summary"] = {"resource_node_count": 2, "edge_count": 1}
    planned = build_aws_topology_detail_diagram_tool_calls(
        _contract(), topology, _shape_library(), {"create_diagram"}
    )
    titles = _titles(planned)
    # inventory still ships (it is the complete answer), but no thin details
    assert titles == ["AWS Topology - Service inventory"]
