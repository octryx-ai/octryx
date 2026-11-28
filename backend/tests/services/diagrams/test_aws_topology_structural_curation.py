"""Curation in the structural AWS overview: folds and aggregates, empty subnet tiers as labeled containers, and a legend that reports coverage gaps and separates partial from failed services."""

from app.services.diagrams.aws_topology_diagram import build_aws_topology_diagram_tool_call
from tests.aws_topology_structural_layout_support import (
    _assert_no_sibling_overlap,
    _cells_by_id,
    _contract,
    _shape_library,
    _topology_result,
)


def _curation_topology():
    topology = _topology_result()
    brief = topology["diagram_brief"]
    brief["selected_nodes"].extend(
        [
            {"ref": "tg1", "type": "target_group", "label": "k8s-app-app-0d2ef54549", "service": "elbv2",
             "attributes": {"vpc_id": "vpc-123"}},
            {"ref": "tg_l1", "type": "target_group", "label": "k8s-orphan-a-91cdee3bc0", "service": "elbv2",
             "attributes": {"vpc_id": "vpc-123"}},
            {"ref": "tg_l2", "type": "target_group", "label": "k8s-orphan-b-91cdee3bc1", "service": "elbv2",
             "attributes": {"vpc_id": "vpc-123"}},
            {"ref": "asg1", "type": "autoscaling_group", "label": "eks-ng-2024081521081053810000000c-e0c8abef-4a6c-8251-046f-bc48a1d1c091", "service": "eks"},
            {"ref": "ng1", "type": "eks_nodegroup", "label": "ng-2024081521081053810000000c", "service": "eks",
             "attributes": {"status": "ACTIVE", "desired_size": 3}},
        ]
    )
    brief["selected_edges"].extend(
        [
            {"source_ref": "alb1", "target_ref": "tg1", "type": "routes_to", "service": "elbv2"},
            {"source_ref": "asg1", "target_ref": "ng1", "type": "backs", "service": "eks"},
            {"source_ref": "ng1", "target_ref": "vpc1", "type": "runs_in", "service": "eks"},
        ]
    )
    return topology


def test_curation_folds_and_aggregates():
    import json

    planned = build_aws_topology_diagram_tool_call(
        _contract(), _curation_topology(), _shape_library(), {"create_diagram"}
    )
    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    cells = _cells_by_id(xml)

    # routed target group folded into its load balancer
    assert "tg1" not in cells
    assert "1 target group" in cells["alb1"].get("value")
    # ASG folded into the nodegroup it backs
    assert "asg1" not in cells
    assert "ASG" in cells["ng1"].get("value")
    # leftover target groups summarized into one node inside the VPC
    assert "tg_l1" not in cells and "tg_l2" not in cells
    assert "2 target groups" in cells["agg_target_groups"].get("value")
    assert cells["agg_target_groups"].get("parent") == "vpc1"
    # names normalized for display
    assert "k8s-app-app" not in xml
    assert "folded into their load balancers" in xml


def test_empty_subnet_tiers_shown_as_labeled_containers():
    import json

    topology = _topology_result()
    brief = topology["diagram_brief"]
    # drop the resources that were placed in a tier -> both tiers become empty
    brief["selected_nodes"] = [n for n in brief["selected_nodes"] if n["ref"] not in {"nat1", "eks1"}]
    brief["selected_edges"] = [
        e for e in brief["selected_edges"] if e["source_ref"] not in {"nat1", "eks1"}
    ]
    planned = build_aws_topology_diagram_tool_call(_contract(), topology, _shape_library(), {"create_diagram"})
    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    cells = _cells_by_id(xml)

    # the individual subnet nodes are never drawn; the tier container is
    assert "pub_a" not in cells and "priv_a" not in cells
    assert "Public subnets (1)" in cells["vpc1__tier_public"].get("value")
    assert "Private subnets (1)" in cells["vpc1__tier_private"].get("value")
    _assert_no_sibling_overlap(xml)


def test_structural_legend_reports_coverage_gaps():
    topology = _topology_result()
    topology["service_summary"] = dict(topology["service_summary"] or {})
    topology["service_summary"]["services_failed"] = ["efs", "ecs"]
    topology["service_summary"]["services_skipped"] = ["route53"]
    planned = build_aws_topology_diagram_tool_call(_contract(), topology, _shape_library(), {"create_diagram"})
    import json

    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    assert "Not readable in this account (permissions/errors): ecs, efs." in xml
    assert "Excluded by project policy: route53." in xml


def test_structural_legend_separates_partial_from_failed_services():
    topology = _topology_result()
    topology["service_summary"] = dict(topology["service_summary"] or {})
    # ec2 worked in one region and failed in another -> partial, not unreadable
    topology["service_summary"]["services_failed"] = ["ec2", "efs"]
    topology["service_summary"]["services_partial"] = ["ec2"]
    planned = build_aws_topology_diagram_tool_call(_contract(), topology, _shape_library(), {"create_diagram"})
    import json

    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    assert "Not readable in this account (permissions/errors): efs." in xml
    assert "Partially readable (failed in at least one region): ec2." in xml


def test_structural_legend_stays_silent_without_coverage_gaps():
    planned = build_aws_topology_diagram_tool_call(
        _contract(), _topology_result(), _shape_library(), {"create_diagram"}
    )
    import json

    xml = json.loads(planned[0]["function"]["arguments"])["xml"]
    assert "Not readable in this account" not in xml
    assert "Excluded by project policy" not in xml
