"""The deterministic AWS topology diagram builder and its large-overview aggregation."""

from app.services.diagrams.aws_topology_diagram import build_aws_topology_diagram_tool_call
from tests.support.task_workflow_support import _tool_args, _tool_name

_AWS_TOPOLOGY_CONTRACT = {"workflow_id": "generic_diagram", "diagram_source": "aws_topology_snapshot", "topic": ""}


def _small_topology_nodes() -> list[dict]:
    return [
        {"ref": "n1", "type": "vpc", "label": "vpc-123", "service": "ec2"},
        {
            "ref": "n2",
            "type": "subnet",
            "label": "private-a",
            "service": "ec2",
            "attributes": {"subnet_tier": "private", "availability_zone": "eu-central-1a"},
        },
        {"ref": "n3", "type": "eks_cluster", "label": "octryx", "service": "eks"},
        {"ref": "n4", "type": "rds_instance", "label": "octryx-db", "service": "rds"},
        {
            "ref": "n5",
            "type": "dynamodb_table",
            "label": "audit-events",
            "service": "dynamodb",
            "attributes": {"status": "ACTIVE", "billing_mode": "PAY_PER_REQUEST"},
        },
        {"ref": "n6", "type": "waf_web_acl", "label": "edge-waf", "service": "wafv2"},
        {"ref": "n7", "type": "load_balancer", "label": "app-alb", "service": "elbv2"},
        {"ref": "n8", "type": "security_group", "label": "db-sg", "service": "ec2"},
        {"ref": "n9", "type": "cidr", "label": "10.0.0.0/24", "service": "ec2"},
    ]


def _small_topology_snapshot() -> dict:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {
            "resource_node_count": 4,
            "edge_count": 3,
            "selected_node_counts_by_service": {"ec2": 2, "eks": 1, "rds": 1},
        },
        "diagram_brief": {
            "mode": "full",
            "selected_nodes": _small_topology_nodes(),
            "selected_edges": [
                {"source_ref": "n2", "target_ref": "n1", "type": "belongs_to", "service": "ec2"},
                {"source_ref": "n3", "target_ref": "n2", "type": "uses_subnet", "service": "eks"},
                {"source_ref": "n4", "target_ref": "n1", "type": "runs_in", "service": "rds"},
                {"source_ref": "n4", "target_ref": "n8", "type": "uses_security_group", "service": "rds"},
                {
                    "source_ref": "n9",
                    "target_ref": "n8",
                    "type": "allows_ingress_to",
                    "service": "ec2",
                    "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432},
                },
                {
                    "source_ref": "n9",
                    "target_ref": "n8",
                    "type": "allows_ingress_to",
                    "service": "ec2",
                    "attributes": {"protocol": "tcp", "from_port": 3306, "to_port": 3306},
                },
                {"source_ref": "n6", "target_ref": "n7", "type": "protects", "service": "wafv2"},
                {
                    "source_ref": "n3",
                    "target_ref": "n1",
                    "type": "belongs_to_account",
                    "service": "eks",
                },
            ],
        },
    }


def _small_shape_catalog() -> dict:
    return {
        "library": "aws4",
        "prefix": "mxgraph.aws4",
        "usage_xml": '<mxCell value="label" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{shape};" vertex="1" parent="1"><mxGeometry x="0" y="0" width="60" height="60" as="geometry" /></mxCell>',
        "matched_shapes": [
            {"requested": "vpc", "shape": "vpc", "match_type": "exact"},
            {"requested": "group_subnet", "shape": "group_subnet", "match_type": "exact"},
            {"requested": "eks", "shape": "eks", "match_type": "exact"},
            {"requested": "rds", "shape": "rds", "match_type": "exact"},
            {"requested": "dynamodb", "shape": "dynamodb", "match_type": "exact"},
            {"requested": "waf", "shape": "waf", "match_type": "exact"},
        ],
    }


def test_aws_topology_deterministic_diagram_builder_is_available_as_fallback():
    contract = _AWS_TOPOLOGY_CONTRACT

    planned = build_aws_topology_diagram_tool_call(
        contract,
        _small_topology_snapshot(),
        _small_shape_catalog(),
        {"create_diagram"},
    )

    assert _tool_name(planned) == "create_diagram"
    args = _tool_args(planned)
    xml = args["xml"]
    assert args["title"] == "AWS Topology Overview"
    assert 'id="aws_cloud"' in xml
    assert "grIcon=mxgraph.aws4.group_vpc2" in xml
    assert 'id="n1"' in xml
    assert 'id="n7"' in xml
    assert "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.eks" in xml
    assert "Private subnets (1)" in xml and "central-1a" in xml
    assert "DynamoDB table / ACTIVE / PAY_PER_REQUEST" in xml
    assert "protects" in xml
    assert 'parent="n1__tier_private"' in xml
    assert 'source="n3" target="n2"' not in xml
    assert 'source="n6" target="n7"' in xml
    assert 'id="n8"' not in xml
    assert "uses security group" not in xml
    assert "ingress tcp/5432" not in xml
    assert "security-group/CIDR nodes are omitted" in xml
    assert 'source="n3" target="n1"' not in xml
    assert "aws_topology_snapshot" in xml
    assert "<mxGraphModel" not in xml
    assert '<mxCell id="0"' not in xml
    assert '<mxCell id="1"' not in xml


def _high_cardinality_graph() -> tuple[list[dict], list[dict]]:
    selected_nodes = [
        {"ref": "vpc1", "type": "vpc", "label": "vpc-123", "service": "ec2"},
        {"ref": "subnet1", "type": "subnet", "label": "private-a", "service": "ec2"},
        {"ref": "rds1", "type": "rds_instance", "label": "app-db", "service": "rds"},
        {"ref": "sg_keep", "type": "security_group", "label": "db-sg", "service": "ec2"},
    ]
    selected_edges = [
        {"source_ref": "rds1", "target_ref": "sg_keep", "type": "uses_security_group", "service": "rds"},
        {"source_ref": "subnet1", "target_ref": "vpc1", "type": "belongs_to", "service": "ec2"},
    ]
    for index in range(75):
        selected_nodes.append(
            {"ref": f"ddb{index}", "type": "dynamodb_table", "label": f"audit-{index}", "service": "dynamodb"}
        )
    for index in range(15):
        selected_nodes.append({"ref": f"s3{index}", "type": "s3_bucket", "label": f"bucket-{index}", "service": "s3"})
    for index in range(20):
        selected_nodes.append({"ref": f"cidr{index}", "type": "cidr", "label": f"10.0.{index}.0/24", "service": "ec2"})
        selected_edges.append(
            {
                "source_ref": f"cidr{index}",
                "target_ref": "sg_keep",
                "type": "allows_ingress_to",
                "service": "ec2",
                "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432},
            }
        )
    for index in range(20):
        selected_nodes.append(
            {"ref": f"sg_other{index}", "type": "security_group", "label": f"unused-sg-{index}", "service": "ec2"}
        )
    return selected_nodes, selected_edges


def _large_shape_catalog() -> dict:
    return {
        "library": "aws4",
        "prefix": "mxgraph.aws4",
        "matched_shapes": [
            {"requested": "vpc", "shape": "vpc", "match_type": "exact"},
            {"requested": "group_subnet", "shape": "group_subnet", "match_type": "exact"},
            {"requested": "rds", "shape": "rds", "match_type": "exact"},
            {"requested": "security_group", "shape": "security_group", "match_type": "exact"},
            {"requested": "dynamodb", "shape": "dynamodb", "match_type": "exact"},
            {"requested": "s3", "shape": "s3", "match_type": "exact"},
        ],
    }


def test_aws_topology_large_overview_aggregates_high_cardinality_nodes():
    contract = _AWS_TOPOLOGY_CONTRACT
    selected_nodes, selected_edges = _high_cardinality_graph()

    planned = build_aws_topology_diagram_tool_call(
        contract,
        {
            "account_id": "123456789012",
            "region": "eu-central-1",
            "service_summary": {
                "resource_node_count": len(selected_nodes),
                "edge_count": len(selected_edges),
            },
            "diagram_brief": {
                "mode": "full",
                "selected_nodes": selected_nodes,
                "selected_edges": selected_edges,
            },
        },
        _large_shape_catalog(),
        {"create_diagram"},
    )

    assert _tool_name(planned) == "create_diagram"
    xml = _tool_args(planned)["xml"]
    assert "75 DynamoDB tables" in xml
    assert "15 S3 buckets" in xml
    assert "audit-74" not in xml
    assert "bucket-14" not in xml
    assert "unused-sg-19" not in xml
    assert "app-db" in xml
    assert "CIDR sources" not in xml
    assert "db-sg" not in xml
    assert "uses security group" not in xml
    assert "security-group/CIDR nodes are omitted" in xml
