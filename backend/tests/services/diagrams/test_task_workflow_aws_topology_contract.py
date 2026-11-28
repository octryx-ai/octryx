"""AWS topology detail candidates and the deterministic detail diagram set for a large snapshot."""

import json

from app.services.diagrams.aws_topology_detail_candidates import build_aws_topology_detail_candidates
from app.services.diagrams.aws_topology_diagram import build_aws_topology_detail_diagram_tool_calls

# The contract the evidence-backed diagram enforcement renders with (no workflow family involved).
_EVIDENCE_CONTRACT = {"diagram_source": "aws_topology_snapshot", "topic": ""}


def _large_aws_topology_result() -> dict:
    nodes = [
        {"ref": "account", "type": "aws_account", "label": "Account", "service": "sts"},
        {"ref": "vpc-main", "type": "vpc", "label": "main-vpc", "service": "ec2"},
        {"ref": "subnet-a", "type": "subnet", "label": "private-a", "service": "ec2"},
        {"ref": "rt-private", "type": "route_table", "label": "private-rt", "service": "ec2"},
        {"ref": "sg-rds", "type": "security_group", "label": "rds-sg", "service": "ec2"},
        {"ref": "cidr-admin", "type": "cidr", "label": "10.0.0.0/24", "service": "ec2"},
        {"ref": "rds-main", "type": "rds_instance", "label": "main-db", "service": "rds"},
    ]
    nodes.extend(
        {
            "ref": f"ddb-{index}",
            "type": "dynamodb_table",
            "label": f"table-{index}",
            "service": "dynamodb",
        }
        for index in range(125)
    )
    edges = [
        {"source_ref": "vpc-main", "target_ref": "account", "type": "belongs_to"},
        {"source_ref": "subnet-a", "target_ref": "vpc-main", "type": "belongs_to"},
        {"source_ref": "subnet-a", "target_ref": "rt-private", "type": "uses_route_table"},
        {"source_ref": "rds-main", "target_ref": "subnet-a", "type": "runs_in"},
        {"source_ref": "rds-main", "target_ref": "sg-rds", "type": "uses_security_group"},
        {
            "source_ref": "cidr-admin",
            "target_ref": "sg-rds",
            "type": "allows_ingress_to",
            "label": "ingress tcp/5432",
        },
    ]
    edges.extend({"source_ref": f"ddb-{index}", "target_ref": "account", "type": "belongs_to"} for index in range(125))
    return {
        "diagram_brief": {
            "mode": "full",
            "selected_nodes": nodes,
            "selected_edges": edges,
        }
    }


def test_aws_topology_large_snapshot_exposes_detail_candidates():
    topology_result = _large_aws_topology_result()

    candidates = build_aws_topology_detail_candidates(topology_result)

    candidate_ids = {candidate["id"] for candidate in candidates}
    assert {"network", "data", "security"} <= candidate_ids
    data_candidate = next(candidate for candidate in candidates if candidate["id"] == "data")
    assert data_candidate["estimated_nodes"] >= 120
    assert "dynamodb_table" in data_candidate["node_types"]



def test_aws_topology_large_snapshot_renders_inventory_then_detail_diagrams():
    planned_details = build_aws_topology_detail_diagram_tool_calls(
        dict(_EVIDENCE_CONTRACT),
        _large_aws_topology_result(),
        {"library": "aws4"},
        {"create_diagram"},
    )

    planned_titles = [json.loads(call["function"]["arguments"])["title"] for call in planned_details]
    # inventory board ships first, then the substance-based detail sections
    assert planned_titles and planned_titles[0] == "AWS Topology - Service inventory"
    assert all(title.startswith("AWS Topology Detail - ") for title in planned_titles[1:])
    assert any("Data services" in title for title in planned_titles)
