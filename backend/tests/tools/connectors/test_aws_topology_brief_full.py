"""The full AWS diagram brief covers every visible service and keeps each edge."""


from app.tools.connectors.aws_topology_brief import build_aws_topology_diagram_brief


def _full_diagram_nodes() -> list[dict]:
    return [
        {"id": "account:1", "type": "aws_account", "label": "123456789012", "service": "sts"},
        {"id": "vpc:vpc-1", "type": "vpc", "label": "vpc-1", "service": "ec2"},
        {"id": "subnet:subnet-1", "type": "subnet", "label": "private-a", "service": "ec2"},
        {"id": "sg:app", "type": "security_group", "label": "app-sg", "service": "ec2"},
        {"id": "cidr:10.0.0.0/24", "type": "cidr", "label": "10.0.0.0/24", "service": "ec2"},
        {"id": "alb:app", "type": "load_balancer", "label": "app-alb", "service": "elbv2"},
        {"id": "tg:app", "type": "target_group", "label": "app-tg", "service": "elbv2"},
        {"id": "eks:cluster", "type": "eks_cluster", "label": "octryx", "service": "eks"},
        {"id": "rds:db", "type": "rds_instance", "label": "octryx-db", "service": "rds"},
        {"id": "lambda:fn", "type": "lambda_function", "label": "sync-worker", "service": "lambda"},
        {"id": "s3:bucket", "type": "s3_bucket", "label": "artifact-bucket", "service": "s3"},
        {"id": "pipeline:base", "type": "codepipeline", "label": "base-apply", "service": "codepipeline"},
        {"id": "waf:web", "type": "waf_web_acl", "label": "edge-waf", "service": "wafv2"},
        {"id": "bedrock:model", "type": "bedrock_model", "label": "catalog-model", "service": "bedrock"},
    ]


def _full_diagram_edges() -> list[dict]:
    return [
        {"source": "alb:app", "target": "tg:app", "type": "routes_to", "service": "elbv2"},
        {"source": "alb:app", "target": "vpc:vpc-1", "type": "runs_in", "service": "elbv2"},
        {"source": "alb:app", "target": "subnet:subnet-1", "type": "uses_subnet", "service": "elbv2"},
        {"source": "eks:cluster", "target": "subnet:subnet-1", "type": "uses_subnet", "service": "eks"},
        {"source": "eks:cluster", "target": "sg:app", "type": "uses_security_group", "service": "eks"},
        {
            "source": "cidr:10.0.0.0/24",
            "target": "sg:app",
            "type": "allows_ingress_to",
            "service": "ec2",
            "attributes": {"protocol": "tcp", "from_port": 5432, "to_port": 5432, "source_type": "cidr"},
        },
        {"source": "rds:db", "target": "vpc:vpc-1", "type": "runs_in", "service": "rds"},
        {"source": "rds:db", "target": "sg:app", "type": "uses_security_group", "service": "rds"},
        {"source": "lambda:fn", "target": "subnet:subnet-1", "type": "uses_subnet", "service": "lambda"},
        {"source": "subnet:subnet-1", "target": "vpc:vpc-1", "type": "belongs_to", "service": "ec2"},
    ]


def _full_diagram_result(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "account_id": "123456789012",
            "region": "eu-central-1",
            "resource_node_count": len(nodes),
            "edge_count": len(edges),
            "inventory_services_with_resources": [
                "codepipeline",
                "ec2",
                "eks",
                "elbv2",
                "lambda",
                "rds",
                "s3",
                "wafv2",
            ],
            "catalog_visibility_services": ["bedrock"],
            "node_counts_by_service": {
                "bedrock": 1,
                "codepipeline": 1,
                "ec2": 4,
                "eks": 1,
                "elbv2": 2,
                "lambda": 1,
                "rds": 1,
                "s3": 1,
                "sts": 1,
                "wafv2": 1,
            },
        },
        "scope": {"diagram_brief_requested": True, "diagram_detail": "full"},
        "nodes": nodes,
        "edges": edges,
        "warnings": [],
    }


def test_aws_topology_snapshot_full_diagram_brief_covers_visible_services():
    nodes = _full_diagram_nodes()
    edges = _full_diagram_edges()
    result = _full_diagram_result(nodes, edges)

    brief = build_aws_topology_diagram_brief(result, {})

    assert brief["mode"] == "full"
    selected_services = {node["service"] for node in brief["selected_nodes"]}
    assert {
        "codepipeline",
        "ec2",
        "eks",
        "elbv2",
        "lambda",
        "rds",
        "s3",
        "wafv2",
    }.issubset(selected_services)
    assert "bedrock" not in selected_services
    assert len(brief["selected_edges"]) == len(edges)
    assert all("ref" in node and "id" not in node for node in brief["selected_nodes"])
    assert all("source_ref" in edge and "source" not in edge for edge in brief["selected_edges"])
    ingress_edge = next(edge for edge in brief["selected_edges"] if edge["type"] == "allows_ingress_to")
    assert ingress_edge["attributes"] == {
        "protocol": "tcp",
        "from_port": 5432,
        "to_port": 5432,
        "source_type": "cidr",
    }
    assert brief["service_coverage"]["selected_node_counts_by_service"]["elbv2"] == 2


