"""Structural (container-based) AWS topology overview layout."""

from app.services.diagrams.aws_topology_diagram import build_aws_topology_diagram_tool_call
from tests.aws_topology_structural_layout_support import (
    _assert_no_sibling_overlap,
    _cells_by_id,
    _contract,
    _multi_region_topology,
    _shape_library,
    _topology_result,
)


def _rendered_xml():
    planned = build_aws_topology_diagram_tool_call(
        _contract(), _topology_result(), _shape_library(), {"create_diagram"}
    )
    assert planned and planned[0]["function"]["name"] == "create_diagram"
    import json

    return json.loads(planned[0]["function"]["arguments"])["xml"]


def test_structural_layout_nests_vpc_tiers_and_resources():
    cells = _cells_by_id(_rendered_xml())

    assert "grIcon=mxgraph.aws4.group_aws_cloud_alt" in cells["aws_cloud"].get("style")
    assert cells["vpc1"].get("parent") == "aws_cloud"
    assert "grIcon=mxgraph.aws4.group_vpc2" in cells["vpc1"].get("style")
    assert "10.0.0.0/16" in cells["vpc1"].get("value")

    # one container per subnet tier, official aws4 group_subnet shape
    pub_tier, priv_tier = "vpc1__tier_public", "vpc1__tier_private"
    assert cells[pub_tier].get("parent") == "vpc1"
    assert "grIcon=mxgraph.aws4.group_subnet" in cells[pub_tier].get("style")
    assert "fillColor=#E9F3E6" in cells[pub_tier].get("style")
    assert "Public subnets" in cells[pub_tier].get("value")
    assert "central-1a" in cells[pub_tier].get("value")
    assert "fillColor=#E6F2F8" in cells[priv_tier].get("style")

    # single-tier resources nest inside their tier container
    assert cells["nat1"].get("parent") == pub_tier
    assert cells["eks1"].get("parent") == priv_tier
    # multi-tier / vpc-level resources sit directly in the VPC container
    assert cells["alb1"].get("parent") == "vpc1"
    assert cells["rds1"].get("parent") == "vpc1"
    assert cells["igw1"].get("parent") == "vpc1"
    # regional services live outside the VPC
    assert cells["ddb1"].get("parent") == "regional_services"


def test_structural_layout_drops_membership_edges_and_security_wiring():
    xml = _rendered_xml()
    cells = _cells_by_id(xml)

    assert "sg1" not in cells
    assert "cidr1" not in cells
    assert "uses security group" not in xml
    assert "ingress tcp/5432" not in xml
    # membership is expressed by nesting, not edges
    assert 'target="vpc1"' not in xml
    assert 'target="vpc1__tier_private"' not in xml
    assert "security-group/CIDR nodes are omitted" in xml


def test_structural_layout_siblings_do_not_overlap():
    _assert_no_sibling_overlap(_rendered_xml())


def test_multi_region_vpcs_render_in_region_frames_with_peering_strip():
    import json

    planned = build_aws_topology_diagram_tool_call(
        _contract(), _multi_region_topology(), _shape_library(), {"create_diagram"}
    )
    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    cells = _cells_by_id(xml)

    # one dashed region frame per region, holding that region's VPC
    assert cells["region_eu-central-1"].get("parent") == "aws_cloud"
    assert "group_region" in cells["region_eu-central-1"].get("style")
    assert cells["vpc1"].get("parent") == "region_eu-central-1"
    assert cells["vpc2"].get("parent") == "region_eu-west-1"

    # regional services stay inside their region frame
    assert cells["ddb1"].get("parent") == "regional_services_eu-central-1"
    assert cells["regional_services_eu-central-1"].get("parent") == "region_eu-central-1"
    assert cells["ddb2"].get("parent") == "regional_services_eu-west-1"

    # the peering connection is an inter-VPC connector, not nested in one VPC
    assert cells["peer1"].get("parent") == "inter_vpc_connectivity"
    edges = {
        (cell.get("source"), cell.get("target"))
        for cell in cells.values()
        if str(cell.get("id") or "").startswith("ivc_")
    }
    assert ("peer1", "vpc1") in edges and ("peer1", "vpc2") in edges

    _assert_no_sibling_overlap(xml)


def test_single_region_topology_renders_without_region_frames():
    xml = _rendered_xml()
    assert "region_eu-central-1" not in xml
    assert "inter_vpc_connectivity" not in xml


def test_structural_layout_grid_fallback_without_graphviz(monkeypatch):
    from app.services.diagrams import aws_structural_autolayout

    monkeypatch.setattr(aws_structural_autolayout, "dot_binary", lambda: None)
    xml = _rendered_xml()
    cells = _cells_by_id(xml)
    assert cells["nat1"].get("parent") == "vpc1__tier_public"
    assert cells["eks1"].get("parent") == "vpc1__tier_private"
    assert cells["ddb1"].get("parent") == "regional_services"
    _assert_no_sibling_overlap(xml)


def test_structural_layout_uses_banded_detail_layout_without_vpc():
    topology = _topology_result()
    brief = topology["diagram_brief"]
    brief["selected_nodes"] = [n for n in brief["selected_nodes"] if n["type"] not in {"vpc", "subnet"}]
    brief["selected_edges"] = []
    planned = build_aws_topology_diagram_tool_call(_contract(), topology, _shape_library(), {"create_diagram"})
    import json

    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    # no service swimlanes; non-VPC selections render role bands
    assert "swimlane" not in xml
    assert "aws_cloud" not in xml
    assert 'id="band_' in xml
