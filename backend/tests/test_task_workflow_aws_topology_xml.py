"""Rendering AWS topology XML from evidence, shapes and the tool message history."""

import json

from app.services.diagrams.aws_topology_diagram import build_aws_topology_diagram_tool_call
from app.services.turn_tool_history import _latest_successful_tool_result, merge_tool_history_from_messages
from tests.task_workflow_support import _tool_args, _tool_name

# The contract the evidence-backed diagram enforcement renders with (no workflow family involved).
_EVIDENCE_CONTRACT = {"diagram_source": "aws_topology_snapshot", "topic": ""}


def _render_from_history(turn_tool_history: list[dict], allowed_tool_names: set[str]) -> list[dict]:
    return build_aws_topology_diagram_tool_call(
        dict(_EVIDENCE_CONTRACT),
        _latest_successful_tool_result(turn_tool_history, "aws_topology_snapshot"),
        _latest_successful_tool_result(turn_tool_history, "get_shape_library"),
        allowed_tool_names,
    )


def test_aws_topology_xml_renders_from_evidence_and_shapes():
    planned = _render_from_history(
        [
            {
                "tool_name": "aws_topology_snapshot",
                "result": {
                    "account_id": "123456789012",
                    "region": "eu-central-1",
                    "service_summary": {
                        "resource_node_count": 4,
                        "edge_count": 3,
                        "selected_node_counts_by_service": {"ec2": 2, "eks": 1, "rds": 1},
                    },
                    "diagram_brief": {
                        "mode": "full",
                        "selected_nodes": [
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
                        ],
                        "selected_edges": [
                            {"source_ref": "n2", "target_ref": "n1", "type": "belongs_to", "service": "ec2"},
                            {"source_ref": "n3", "target_ref": "n2", "type": "uses_subnet", "service": "eks"},
                            {"source_ref": "n4", "target_ref": "n1", "type": "runs_in", "service": "rds"},
                            {"source_ref": "n6", "target_ref": "n7", "type": "protects", "service": "wafv2"},
                            {
                                "source_ref": "n3",
                                "target_ref": "n1",
                                "type": "belongs_to_account",
                                "service": "eks",
                            },
                        ],
                    },
                },
            },
            {
                "tool_name": "get_shape_library",
                "result": {
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
                },
            },
        ],
        {"aws_topology_snapshot", "get_shape_library", "create_diagram"},
    )

    assert _tool_name(planned) == "create_diagram"
    xml = _tool_args(planned)["xml"]
    assert "AWS Topology" in _tool_args(planned)["title"]
    assert "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.eks" in xml
    assert "DynamoDB table / ACTIVE / PAY_PER_REQUEST" in xml
    assert "protects" in xml


def test_aws_topology_xml_renders_from_tool_message_history():
    messages = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "_artifact_kind": "tool_result",
                    "artifact_id": "topology-artifact",
                    "tool_name": "aws_topology_snapshot",
                    "result": {
                        "account_id": "123456789012",
                        "region": "eu-central-1",
                        "service_summary": {"resource_node_count": 2, "edge_count": 1},
                        "diagram_brief": {
                            "mode": "full",
                            "selected_nodes": [
                                {"ref": "vpc1", "type": "vpc", "label": "vpc-1", "service": "ec2"},
                                {"ref": "eks1", "type": "eks_cluster", "label": "octryx", "service": "eks"},
                            ],
                            "selected_edges": [
                                {"source_ref": "eks1", "target_ref": "vpc1", "type": "runs_in", "service": "eks"}
                            ],
                        },
                    },
                }
            ),
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "_artifact_kind": "tool_result",
                    "artifact_id": "shape-artifact",
                    "tool_name": "get_shape_library",
                    "result": {
                        "library": "aws4",
                        "prefix": "mxgraph.aws4",
                        "matched_shapes": [{"requested": "eks", "shape": "eks", "match_type": "exact"}],
                    },
                }
            ),
        },
    ]

    planned = _render_from_history(merge_tool_history_from_messages([], messages), {"create_diagram"})

    assert _tool_name(planned) == "create_diagram"
    xml = _tool_args(planned)["xml"]
    assert "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.eks" in xml
    assert "octryx" in xml
