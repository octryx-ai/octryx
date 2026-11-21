"""Shared helpers for the test_aws_topology_structural_layout_* modules."""

import xml.etree.ElementTree as ET


def _contract():
    return {"workflow_id": "generic_diagram", "diagram_source": "aws_topology_snapshot", "topic": ""}


def _shape_library():
    return {
        "library": "aws4",
        "prefix": "mxgraph.aws4",
        "matched_shapes": [
            {"requested": "vpc", "shape": "vpc", "match_type": "exact"},
            {"requested": "nat_gateway", "shape": "nat_gateway", "match_type": "exact"},
            {"requested": "internet_gateway", "shape": "internet_gateway", "match_type": "exact"},
            {"requested": "application_load_balancer", "shape": "application_load_balancer", "match_type": "exact"},
            {"requested": "eks", "shape": "eks", "match_type": "exact"},
            {"requested": "rds", "shape": "rds", "match_type": "exact"},
            {"requested": "dynamodb", "shape": "dynamodb", "match_type": "exact"},
            {"requested": "s3", "shape": "s3", "match_type": "exact"},
        ],
    }


def _topology_result():
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {"resource_node_count": 11, "edge_count": 12},
        "diagram_brief": {
            "mode": "full",
            "selected_nodes": [
                {"ref": "vpc1", "type": "vpc", "label": "vpc-123", "service": "ec2", "attributes": {"cidr_block": "10.0.0.0/16"}},
                {
                    "ref": "pub_a",
                    "type": "subnet",
                    "label": "subnet-pub-a",
                    "service": "ec2",
                    "attributes": {"subnet_tier": "public", "availability_zone": "eu-central-1a"},
                },
                {
                    "ref": "priv_a",
                    "type": "subnet",
                    "label": "subnet-priv-a",
                    "service": "ec2",
                    "attributes": {"subnet_tier": "private", "availability_zone": "eu-central-1a"},
                },
                {"ref": "nat1", "type": "nat_gateway", "label": "nat-1", "service": "ec2"},
                {"ref": "igw1", "type": "internet_gateway", "label": "igw-1", "service": "ec2"},
                {"ref": "alb1", "type": "load_balancer", "label": "app-alb", "service": "elbv2"},
                {"ref": "eks1", "type": "eks_cluster", "label": "octryx", "service": "eks"},
                {"ref": "rds1", "type": "rds_instance", "label": "app-db", "service": "rds"},
                {"ref": "ddb1", "type": "dynamodb_table", "label": "audit-events", "service": "dynamodb"},
                {"ref": "sg1", "type": "security_group", "label": "db-sg", "service": "ec2"},
                {"ref": "cidr1", "type": "cidr", "label": "10.1.0.0/24", "service": "ec2"},
            ],
            "selected_edges": [
                {"source_ref": "pub_a", "target_ref": "vpc1", "type": "belongs_to", "service": "ec2"},
                {"source_ref": "priv_a", "target_ref": "vpc1", "type": "belongs_to", "service": "ec2"},
                {"source_ref": "nat1", "target_ref": "pub_a", "type": "runs_in", "service": "ec2"},
                {"source_ref": "igw1", "target_ref": "vpc1", "type": "attached_to", "service": "ec2"},
                # ALB spans both subnets -> VPC level, not inside a subnet.
                {"source_ref": "alb1", "target_ref": "pub_a", "type": "uses_subnet", "service": "elbv2"},
                {"source_ref": "alb1", "target_ref": "priv_a", "type": "uses_subnet", "service": "elbv2"},
                {"source_ref": "eks1", "target_ref": "priv_a", "type": "uses_subnet", "service": "eks"},
                {"source_ref": "rds1", "target_ref": "vpc1", "type": "runs_in", "service": "rds"},
                {"source_ref": "rds1", "target_ref": "sg1", "type": "uses_security_group", "service": "rds"},
                {
                    "source_ref": "cidr1",
                    "target_ref": "sg1",
                    "type": "allows_ingress_to",
                    "service": "ec2",
                    "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432},
                },
            ],
        },
    }


def _cells_by_id(xml: str) -> dict[str, ET.Element]:
    root = ET.fromstring(f"<mxGraphModel><root>{xml}</root></mxGraphModel>")
    return {cell.get("id"): cell for cell in root.iter("mxCell")}


def _sibling_rects_by_parent(xml: str) -> dict[str, list[tuple[str, float, float, float, float]]]:
    root = ET.fromstring(f"<mxGraphModel><root>{xml}</root></mxGraphModel>")
    by_parent: dict[str, list[tuple[str, float, float, float, float]]] = {}
    for cell in root.iter("mxCell"):
        if cell.get("edge") == "1":
            continue
        geometry = cell.find("mxGeometry")
        parent = cell.get("parent")
        if geometry is None or parent in {None, "1"}:
            continue
        by_parent.setdefault(parent, []).append(
            (
                cell.get("id"),
                float(geometry.get("x") or 0),
                float(geometry.get("y") or 0),
                float(geometry.get("width") or 0),
                float(geometry.get("height") or 0),
            )
        )
    return by_parent


def _assert_no_sibling_overlap(xml: str) -> None:
    import itertools

    for parent, siblings in _sibling_rects_by_parent(xml).items():
        for a, b in itertools.combinations(siblings, 2):
            separated = (
                a[1] + a[3] <= b[1]
                or b[1] + b[3] <= a[1]
                or a[2] + a[4] <= b[2]
                or b[2] + b[4] <= a[2]
            )
            assert separated, f"{a[0]} overlaps {b[0]} inside {parent}"


def _multi_region_topology():
    """Two VPCs in two regions, connected by a peering connection; one
    regional service per region."""
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {"resource_node_count": 9, "edge_count": 8},
        "diagram_brief": {
            "mode": "full",
            "selected_nodes": [
                {"ref": "vpc1", "type": "vpc", "label": "vpc-main", "service": "ec2",
                 "region": "eu-central-1", "attributes": {"cidr_block": "10.0.0.0/16"}},
                {"ref": "vpc2", "type": "vpc", "label": "vpc-dr", "service": "ec2",
                 "region": "eu-west-1", "attributes": {"cidr_block": "10.1.0.0/16"}},
                {"ref": "pub1", "type": "subnet", "label": "main-pub", "service": "ec2",
                 "region": "eu-central-1",
                 "attributes": {"subnet_tier": "public", "availability_zone": "eu-central-1a"}},
                {"ref": "pub2", "type": "subnet", "label": "dr-pub", "service": "ec2",
                 "region": "eu-west-1",
                 "attributes": {"subnet_tier": "public", "availability_zone": "eu-west-1a"}},
                {"ref": "nat1", "type": "nat_gateway", "label": "main-nat", "service": "ec2",
                 "region": "eu-central-1"},
                {"ref": "rds2", "type": "rds_instance", "label": "dr-db", "service": "rds",
                 "region": "eu-west-1"},
                {"ref": "peer1", "type": "vpc_peering", "label": "pcx-1", "service": "ec2",
                 "region": "eu-central-1"},
                {"ref": "ddb1", "type": "dynamodb_table", "label": "events-main", "service": "dynamodb",
                 "region": "eu-central-1"},
                {"ref": "ddb2", "type": "dynamodb_table", "label": "events-dr", "service": "dynamodb",
                 "region": "eu-west-1"},
            ],
            "selected_edges": [
                {"source_ref": "pub1", "target_ref": "vpc1", "type": "belongs_to", "service": "ec2"},
                {"source_ref": "pub2", "target_ref": "vpc2", "type": "belongs_to", "service": "ec2"},
                {"source_ref": "nat1", "target_ref": "pub1", "type": "runs_in", "service": "ec2"},
                {"source_ref": "rds2", "target_ref": "vpc2", "type": "runs_in", "service": "rds"},
                {"source_ref": "peer1", "target_ref": "vpc1", "type": "runs_in", "service": "ec2"},
                {"source_ref": "peer1", "target_ref": "vpc2", "type": "runs_in", "service": "ec2"},
            ],
        },
    }
