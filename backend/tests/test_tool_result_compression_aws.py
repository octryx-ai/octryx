"""AWS topology snapshot compression: service summary priority, working set budget, bounded diagram brief and evidence contract."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.tool_result_compression import compress_tool_result_for_model
from app.services.tool_result_compression.registry import get_strategy_handler
from app.services.tool_result_compression.support import _estimate_tokens


def test_aws_topology_snapshot_compression_prioritizes_service_summary():
    handler = get_strategy_handler("aws_topology_snapshot_summary")
    assert handler is not None

    result = {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-06-01T11:45:00+00:00",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "inventory_services_with_resources": ["ec2", "eks", "rds"],
            "catalog_visibility_services": ["bedrock"],
            "node_counts_by_service": {"ec2": 3, "eks": 1, "rds": 1, "bedrock": 20},
            "services_failed": [],
        },
        "scope": {"services_requested": ["ec2", "eks", "rds", "bedrock"]},
        "nodes": [
            {
                "id": "vpc:vpc-1",
                "type": "vpc",
                "label": "vpc-1",
                "service": "ec2",
                "region": "eu-central-1",
                "arn": None,
                "attributes": {"cidr_block": "10.0.0.0/16", "state": "available", "extra": "ignored"},
            },
            {
                "id": "eks_cluster:risk",
                "type": "eks_cluster",
                "label": "risk",
                "service": "eks",
                "region": "eu-central-1",
                "arn": "arn:aws:eks:eu-central-1:123456789012:cluster/shop",
                "attributes": {"status": "ACTIVE", "version": "1.31"},
            },
        ],
        "warnings": [{"service": "eks", "operation": "describe-cluster", "message": "denied" * 200}],
        "diagram_hints": {"suggested_views": ["network"]},
    }

    compact = handler(result, {"max_nodes_per_service": 1, "max_warnings": 1})

    assert compact["service_summary"]["inventory_services_with_resources"] == ["ec2", "eks", "rds"]
    assert compact["answer_guidance"][2].startswith("If a service is listed in services_partial")
    assert compact["sampled_nodes_by_service"]["ec2"][0]["attributes"] == {
        "state": "available",
        "cidr_block": "10.0.0.0/16",
    }
    assert compact["warning_count"] == 1
    assert len(compact["warnings"][0]["message"]) <= 500


def test_aws_topology_snapshot_default_compression_stays_under_working_set_budget():
    handler = get_strategy_handler("aws_topology_snapshot_summary")
    assert handler is not None

    result = {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-06-01T11:45:00+00:00",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "account_id": "123456789012",
            "region": "eu-central-1",
            "resource_node_count": 127,
            "edge_count": 230,
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
            "identity_evidence_services": ["sts"],
            "catalog_visibility_services": ["bedrock"],
            "services_partial": ["eks"],
            "services_failed": ["eks"],
            "services_skipped": [],
            "node_counts_by_service": {
                "bedrock": 25,
                "codepipeline": 9,
                "ec2": 50,
                "eks": 1,
                "elbv2": 22,
                "lambda": 1,
                "rds": 2,
                "s3": 15,
                "sts": 1,
                "wafv2": 1,
            },
            "node_counts_by_type": {
                "aws_account": 1,
                "bedrock_model": 25,
                "cidr": 15,
                "codepipeline": 9,
                "eks_cluster": 1,
                "lambda_function": 1,
                "load_balancer": 6,
                "rds_instance": 2,
                "s3_bucket": 15,
                "security_group": 25,
                "subnet": 9,
                "target_group": 16,
                "vpc": 1,
                "waf_web_acl": 1,
            },
            "warning_count": 1,
            "warning_counts_by_service": {"eks": 1},
            "warnings_by_service": {
                "eks": [
                    {
                        "operation": "describe-cluster",
                        "severity": "warning",
                        "message": "Parameter validation failed",
                    }
                ]
            },
            "interpretation_notes": [
                "Topology inventory shows visible resources and catalog visibility, not proof of recent runtime usage.",
                "Use Cost Explorer, CloudTrail, or service metrics when the user asks for confirmed active usage.",
            ],
        },
        "scope": {"services_requested": ["sts", "ec2", "eks"], "project_ids": ["project"] * 20},
        "nodes": [{"service": "ec2", "id": f"node-{idx}", "attributes": {"extra": "x" * 500}} for idx in range(200)],
        "warnings": [{"service": "eks", "operation": "describe-cluster", "message": "warning" * 200}],
    }

    compact = handler(result, {})

    assert compact["sampled_nodes_by_service"] == {}
    assert "diagram_brief" not in compact
    assert compact["service_summary"]["services_partial"] == ["eks"]
    assert "project_ids" not in compact["scope"]
    assert _estimate_tokens(compact) < 2200


def test_aws_topology_snapshot_compression_adds_bounded_diagram_brief_when_requested():
    handler = get_strategy_handler("aws_topology_snapshot_summary")
    assert handler is not None

    result = {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "generated_at": "2026-06-01T11:45:00+00:00",
        "service_summary": {
            "evidence_kind": "aws_topology_inventory",
            "resource_node_count": 5,
            "edge_count": 3,
            "inventory_services_with_resources": ["ec2", "eks", "elbv2"],
        },
        "scope": {
            "services_requested": ["sts", "ec2", "elbv2", "eks"],
            "diagram_brief_requested": True,
        },
        "nodes": [
            {"id": "account:1", "type": "aws_account", "label": "123456789012", "service": "sts"},
            {"id": "vpc:vpc-1", "type": "vpc", "label": "vpc-1", "service": "ec2"},
            {"id": "subnet:subnet-1", "type": "subnet", "label": "private-a", "service": "ec2"},
            {"id": "alb:app", "type": "load_balancer", "label": "app-alb", "service": "elbv2"},
            {"id": "eks:cluster", "type": "eks_cluster", "label": "octryx", "service": "eks"},
            {"id": "model:haiku", "type": "bedrock_model", "label": "Claude Haiku", "service": "bedrock"},
        ],
        "edges": [
            {
                "source": "alb:app",
                "target": "subnet:subnet-1",
                "type": "uses_subnet",
                "service": "elbv2",
                "evidence": [{"service": "elbv2", "operation": "describe-load-balancers", "path": "Subnets"}],
            },
            {
                "source": "eks:cluster",
                "target": "subnet:subnet-1",
                "type": "uses_subnet",
                "service": "eks",
                "evidence": [{"service": "eks", "operation": "describe-cluster", "path": "resourcesVpcConfig"}],
            },
            {
                "source": "subnet:subnet-1",
                "target": "vpc:vpc-1",
                "type": "belongs_to",
                "service": "ec2",
                "evidence": [{"service": "ec2", "operation": "describe-subnets", "path": "VpcId"}],
            },
        ],
        "warnings": [],
    }

    compact = handler(result, {"max_diagram_nodes": 5, "max_diagram_edges": 2})

    assert compact["scope"]["diagram_brief_requested"] is True
    brief = compact["diagram_brief"]
    assert brief["mode"] == "compact"
    assert brief["node_count"] == 6
    assert brief["edge_count"] == 3
    assert len(brief["selected_nodes"]) <= 5
    assert len(brief["selected_edges"]) <= 2
    assert all(edge["type"] in {"uses_subnet", "belongs_to"} for edge in brief["selected_edges"])
    assert not any(node["type"] == "bedrock_model" for node in brief["selected_nodes"])
    assert "Use only selected_edges" in brief["notes"][0]


@pytest.mark.asyncio
async def test_aws_topology_snapshot_compression_attaches_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compact = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="aws_topology_snapshot",
        result={
            "account_id": "123456789012",
            "region": "eu-central-1",
            "generated_at": "2026-06-01T11:45:00+00:00",
            "service_summary": {
                "evidence_kind": "aws_topology_inventory",
                "inventory_services_with_resources": ["ec2", "rds"],
                "node_counts_by_service": {"ec2": 2, "rds": 1},
                "services_failed": [],
            },
            "scope": {"services_requested": ["ec2", "rds"], "diagram_brief_requested": True},
            "nodes": [
                {"id": "vpc:vpc-1", "type": "vpc", "label": "vpc-1", "service": "ec2"},
                {"id": "sg:sg-1", "type": "security_group", "label": "app-sg", "service": "ec2"},
                {"id": "rds:db", "type": "rds_instance", "label": "db", "service": "rds"},
            ],
            "edges": [
                {
                    "source": "rds:db",
                    "target": "sg:sg-1",
                    "type": "uses_security_group",
                    "service": "rds",
                    "evidence": [{"service": "rds", "operation": "describe-db-instances", "path": "VpcSecurityGroups"}],
                },
                {"source": "sg:sg-1", "target": "vpc:vpc-1", "type": "belongs_to", "service": "ec2"},
            ],
        },
    )

    contract = compact["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["evidence_state"] == "compact_evidence"
    assert contract["missing_paths"] == []
    assert contract["hard_capped"] is False
    assert "diagram_brief.selected_edges" in contract["required_paths"]
    assert compact["diagram_brief"]["selected_edges"][0]["type"] == "uses_security_group"
