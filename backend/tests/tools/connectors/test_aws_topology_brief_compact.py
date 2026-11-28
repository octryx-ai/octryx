"""The compact AWS diagram brief stays small for a large topology."""

from app.tools.connectors.aws_topology_brief import build_aws_topology_diagram_brief


def test_the_compact_brief_stays_small_for_a_large_topology():
    nodes = [
        {
            "id": "account:123456789012",
            "type": "aws_account",
            "label": "123456789012",
            "service": "sts",
            "attributes": {"extra": "ignored" * 100},
        },
        {
            "id": "vpc:vpc-1",
            "type": "vpc",
            "label": "vpc-1",
            "service": "ec2",
            "region": "eu-central-1",
            "attributes": {"cidr_block": "10.0.0.0/16", "state": "available", "extra": "ignored" * 100},
        },
    ]
    for idx in range(1, 60):
        nodes.append(
            {
                "id": f"subnet:subnet-{idx}",
                "type": "subnet",
                "label": f"private-{idx}",
                "service": "ec2",
                "region": "eu-central-1",
                "attributes": {"availability_zone": "eu-central-1a", "extra": "ignored" * 100},
            }
        )
    for idx in range(1, 25):
        nodes.append(
            {
                "id": f"bedrock:model-{idx}",
                "type": "bedrock_model",
                "label": f"catalog-model-{idx}",
                "service": "bedrock",
            }
        )

    edges = [
        {
            "source": f"subnet:subnet-{idx}",
            "target": "vpc:vpc-1",
            "type": "belongs_to",
            "service": "ec2",
            "evidence": [
                {
                    "service": "ec2",
                    "operation": "describe-subnets",
                    "path": "Subnets[].VpcId",
                    "direct": True,
                    "verbose": "ignored" * 100,
                }
            ],
        }
        for idx in range(1, 60)
    ]

    result = {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "account_id": "123456789012",
            "region": "eu-central-1",
            "resource_node_count": len(nodes),
            "edge_count": len(edges),
            "inventory_services_with_resources": ["ec2"],
            "catalog_visibility_services": ["bedrock"],
            "node_counts_by_service": {"ec2": 60, "bedrock": 24, "sts": 1},
            "node_counts_by_type": {"subnet": 59, "bedrock_model": 24},
            "warnings_by_service": {"ec2": [{"message": "ignored" * 100}]},
        },
        "scope": {"diagram_brief_requested": True},
        "nodes": nodes,
        "edges": edges,
        "warnings": [{"service": "ec2", "operation": "describe-subnets", "message": "warning" * 200}],
    }

    brief = build_aws_topology_diagram_brief(result, {})

    assert brief["mode"] == "compact"
    assert len(brief["selected_nodes"]) <= 8
    assert len(brief["selected_edges"]) <= 8
    assert not any(node["type"] == "bedrock_model" for node in brief["selected_nodes"])
