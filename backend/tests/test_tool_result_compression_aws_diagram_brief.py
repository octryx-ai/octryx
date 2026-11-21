"""The compact AWS diagram brief stays small for a large topology and survives the hard result cap."""

from app.services.tool_result_compression.budget import enforce_compact_result_budget
from app.services.tool_result_compression.registry import get_strategy_handler
from app.services.tool_result_compression.support import _estimate_tokens


def test_aws_topology_snapshot_diagram_brief_stays_small_for_large_topology():
    handler = get_strategy_handler("aws_topology_snapshot_summary")
    assert handler is not None

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

    compact = handler(result, {})

    assert "sampled_nodes_by_service" not in compact
    assert "diagram_hints" not in compact
    assert "warnings_by_service" not in compact["service_summary"]
    assert len(compact["diagram_brief"]["selected_nodes"]) <= 8
    assert len(compact["diagram_brief"]["selected_edges"]) <= 8
    assert not any(node["type"] == "bedrock_model" for node in compact["diagram_brief"]["selected_nodes"])
    assert _estimate_tokens(compact) < 1600


def test_compact_diagram_brief_survives_hard_result_cap():
    """Regression: the hard cap must never replace a diagram-path compact
    result with a brief-less ``_hard_capped`` stub — the evidence-backed
    diagram pipeline requires ``diagram_brief`` in the turn history."""
    brief_nodes = [
        {
            "id": f"subnet:subnet-{index}",
            "type": "subnet",
            "label": f"private-subnet-{index}",
            "service": "ec2",
            "region": "eu-central-1",
        }
        for index in range(1, 9)
    ]
    brief_edges = [
        {
            "source": f"subnet:subnet-{index}",
            "target": "subnet:subnet-1",
            "source_label": f"private-subnet-{index}",
            "target_label": "private-subnet-1",
            "type": "belongs_to",
            "service": "ec2",
        }
        for index in range(2, 9)
    ]
    compact = {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-07-18T09:00:00+00:00",
        # Oversized sibling payload: this is what pushed real compact-detail
        # results over the working-set budget and produced the stub.
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "node_counts_by_type": {f"resource_type_{index}": index for index in range(400)},
            "interpretation_notes": ["note " * 40] * 40,
        },
        "scope": {"diagram_brief_requested": True, "diagram_detail": "compact"},
        "answer_guidance": ["Use diagram_brief.selected_nodes and selected_edges as the only relationship evidence."],
        "diagram_brief": {
            "mode": "compact",
            "node_count": len(brief_nodes),
            "edge_count": len(brief_edges),
            "selected_nodes": brief_nodes,
            "selected_edges": brief_edges,
            "service_coverage": {"inventory_services_with_resources": ["ec2"]},
            "notes": ["Compact mode requested: keep the diagram intentionally small and readable."],
        },
    }
    assert _estimate_tokens(compact) > 2200

    budgeted = enforce_compact_result_budget(compact, token_budget=2200)

    assert _estimate_tokens(budgeted) <= 2200
    brief = budgeted["diagram_brief"]
    assert brief["mode"] == "compact"
    assert brief["selected_nodes"], "diagram_brief must keep a non-empty node selection"
    kept_node_ids = {node["id"] for node in brief["selected_nodes"]}
    for edge in brief["selected_edges"]:
        assert edge["source"] in kept_node_ids
        assert edge["target"] in kept_node_ids
    # The result is still explicitly marked as capped for evidence contracts.
    assert budgeted["_hard_capped"] is True
