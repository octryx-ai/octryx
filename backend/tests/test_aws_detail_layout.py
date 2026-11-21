"""Curated banded flow layout for AWS detail diagrams (non-VPC selections)."""

import json
import xml.etree.ElementTree as ET

from app.services.diagrams.aws_topology_diagram import (
    build_aws_topology_detail_diagram_tool_calls,
)
from tests.aws_topology_structural_layout_support import _contract, _shape_library


def _security_topology():
    """Realistic security-detail evidence: two CIDRs and a peer SG admit
    traffic into SGs used by nodegroups (identical wiring x3) and one RDS."""
    nodes = [
        {"ref": "cidr_a", "type": "cidr", "label": "10.135.32.0/22", "service": "ec2"},
        {"ref": "cidr_b", "type": "cidr", "label": "10.135.36.0/22", "service": "ec2"},
        {"ref": "sg_lb", "type": "security_group", "label": "lb-sg", "service": "ec2"},
        {"ref": "sg_node", "type": "security_group", "label": "node-sg", "service": "ec2"},
        {"ref": "sg_db", "type": "security_group", "label": "db-sg", "service": "ec2"},
        {"ref": "lb1", "type": "load_balancer", "label": "app-alb", "service": "elbv2"},
        {"ref": "rds1", "type": "rds_instance", "label": "app-db", "service": "rds"},
    ] + [
        {"ref": f"ng{i}", "type": "eks_nodegroup", "label": f"ng-{i}", "service": "eks"}
        for i in range(3)
    ]
    edges = [
        {
            "source_ref": "cidr_a",
            "target_ref": "sg_db",
            "type": "allows_ingress_to",
            "service": "ec2",
            "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432},
        },
        {
            "source_ref": "cidr_b",
            "target_ref": "sg_db",
            "type": "allows_ingress_to",
            "service": "ec2",
            "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432},
        },
        {
            "source_ref": "sg_lb",
            "target_ref": "sg_node",
            "type": "allows_ingress_to",
            "service": "ec2",
            "attributes": {"protocol": "tcp", "from_port": 443, "to_port": 443},
        },
        {"source_ref": "lb1", "target_ref": "sg_lb", "type": "uses_security_group", "service": "elbv2"},
        {"source_ref": "rds1", "target_ref": "sg_db", "type": "uses_security_group", "service": "rds"},
    ] + [
        {"source_ref": f"ng{i}", "target_ref": "sg_node", "type": "uses_security_group", "service": "eks"}
        for i in range(3)
    ]
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {"resource_node_count": len(nodes), "edge_count": len(edges)},
        "diagram_brief": {"mode": "full", "selected_nodes": nodes, "selected_edges": edges},
    }


def _planned_by_title(planned, fragment):
    for call in planned:
        args = json.loads(call["function"]["arguments"])
        if fragment in args["title"]:
            return args
    raise AssertionError(f"no planned diagram with title containing {fragment!r}")


def _security_detail_xml():
    planned = build_aws_topology_detail_diagram_tool_calls(
        _contract(), _security_topology(), _shape_library(), {"create_diagram"}, max_diagrams=1
    )
    assert planned and planned[0]["function"]["name"] == "create_diagram"
    return _planned_by_title(planned, "Security group")["xml"]


def _cells_by_id(xml: str) -> dict[str, ET.Element]:
    root = ET.fromstring(f"<mxGraphModel><root>{xml}</root></mxGraphModel>")
    return {cell.get("id"): cell for cell in root.iter("mxCell")}


def test_security_detail_renders_role_bands_top_down():
    cells = _cells_by_id(_security_detail_xml())

    assert "swimlane" not in ET.tostring(cells["band_0"], encoding="unicode")
    bands = {cid: cell for cid, cell in cells.items() if cid.startswith("band_")}
    assert "Traffic sources" in bands["band_0"].get("value")
    assert "Security groups" in bands["band_1"].get("value")

    def band_y(cid):
        return float(bands[cid].find("mxGeometry").get("y"))

    ordered = sorted(bands, key=band_y)
    assert ordered[0] == "band_0" and ordered[1] == "band_1"
    # all bands share x and width (single column, no side-by-side drift)
    geos = [bands[cid].find("mxGeometry") for cid in bands]
    assert len({geo.get("x") for geo in geos}) == 1
    assert len({geo.get("width") for geo in geos}) == 1


def test_security_detail_folds_identical_wiring():
    cells = _cells_by_id(_security_detail_xml())

    # the three nodegroups share one SG and no other wiring -> one counted
    # node with a TYPE-based label (never the first member's name)
    folded = [cell for cell in cells.values() if "3 x EKS nodegroups" in str(cell.get("value") or "")]
    assert folded, "expected the identically wired nodegroups to fold into one typed node"
    assert "ng1" not in cells and "ng2" not in cells
    # the two CIDRs hit the same SG on the same port -> folded, but CIDRs keep
    # the address because it IS the information
    assert any("2 x 10.135" in str(cell.get("value") or "") for cell in cells.values())


def test_security_detail_labels_ingress_edges_with_ports():
    xml = _security_detail_xml()
    assert "ingress tcp/5432" in xml
    assert "ingress tcp/443" in xml


def test_detail_legend_reports_coverage_gaps():
    topology = _security_topology()
    topology["service_summary"] = dict(topology["service_summary"] or {})
    topology["service_summary"]["services_failed"] = ["cloudfront"]
    planned = build_aws_topology_detail_diagram_tool_calls(
        _contract(), topology, _shape_library(), {"create_diagram"}, max_diagrams=1
    )
    xml = _planned_by_title(planned, "Security group")["xml"]
    assert "Not readable in this account (permissions/errors): cloudfront." in xml


def test_detail_band_members_stay_inside_their_band():
    cells = _cells_by_id(_security_detail_xml())
    for cid, cell in cells.items():
        parent = str(cell.get("parent") or "")
        if not parent.startswith("band_"):
            continue
        geo = cell.find("mxGeometry")
        band_geo = cells[parent].find("mxGeometry")
        assert float(geo.get("x")) >= 0 and float(geo.get("y")) >= 0
        assert float(geo.get("x")) + float(geo.get("width")) <= float(band_geo.get("width"))
