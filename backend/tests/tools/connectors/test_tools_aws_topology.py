"""Tests for AWS topology snapshot tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_topology_common
from app.tools.registry import execute_tool
from tests.tools.connectors.aws_tool_context_support import aws_tool_context
from tests.tools.connectors.tools_aws_topology_support import fake_topology_aws_json


def _assert_security_group_edges(result) -> None:
    db_ingress_edges = [
        edge
        for edge in result["edges"]
        if edge["type"] == "allows_ingress_to"
        and edge["target"] == "security_group:sg-1"
        and edge["source"] == "security_group:sg-2"
    ]
    assert {edge["attributes"]["to_port"] for edge in db_ingress_edges} == {3306, 5432}
    db_ingress_edge = next(edge for edge in db_ingress_edges if edge["attributes"]["to_port"] == 5432)
    assert db_ingress_edge["attributes"] == {
        "protocol": "tcp",
        "from_port": 5432,
        "to_port": 5432,
        "source_type": "security_group",
    }
    egress_edge = next(edge for edge in result["edges"] if edge["type"] == "allows_egress_to")
    assert egress_edge["attributes"]["protocol"] == "tcp"
    assert egress_edge["attributes"]["to_port"] == 443


def _assert_subnet_and_service_summary(result) -> None:
    subnet = next(node for node in result["nodes"] if node["id"] == "subnet:subnet-1")
    assert subnet["attributes"]["subnet_tier"] == "db"
    assert subnet["attributes"]["route_table_id"] == "rtb-1"
    assert "network" in result["diagram_hints"]["suggested_views"]
    summary = result["service_summary"]
    assert summary["evidence_kind"] == "aws_topology_inventory"
    assert summary["inventory_services_with_resources"] == [
        "codepipeline",
        "dynamodb",
        "ec2",
        "eks",
        "elbv2",
        "rds",
        "wafv2",
    ]
    assert summary["node_counts_by_service"]["ec2"] >= 3
    assert summary["node_counts_by_service"]["eks"] == 3
    assert summary["node_counts_by_service"]["dynamodb"] == 1
    assert "Topology inventory shows visible resources" in summary["interpretation_notes"][0]


@pytest.mark.asyncio
async def test_aws_topology_snapshot_builds_diagram_ready_graph(monkeypatch):
    monkeypatch.setattr(aws_topology_common, "_aws_json", fake_topology_aws_json)

    result = await execute_tool(
        "aws_topology_snapshot",
        {
            "services": ["ec2", "elbv2", "eks", "rds", "dynamodb", "codepipeline", "wafv2"],
            "max_items": 20,
            "diagram_brief": True,
            "diagram_detail": "full",
        },
        aws_tool_context(),
    )

    node_types = {node["type"] for node in result["nodes"]}
    edge_types = {edge["type"] for edge in result["edges"]}
    assert result["account_id"] == "123456789012"
    assert {"aws_account", "vpc", "subnet", "security_group", "eks_cluster", "eks_nodegroup"}.issubset(node_types)
    assert {"rds_instance", "dynamodb_table", "codepipeline", "waf_web_acl", "load_balancer"}.issubset(node_types)
    assert {"target_group", "internet_gateway", "route_table", "autoscaling_group"}.issubset(node_types)
    assert {"belongs_to", "runs_in", "uses_security_group", "routes_to", "belongs_to_account"}.issubset(edge_types)
    assert {"protects", "uses_route_table", "backs"}.issubset(edge_types)
    assert {"allows_ingress_to", "allows_egress_to"}.issubset(edge_types)
    assert all(node["evidence"] for node in result["nodes"])
    assert result["diagram_brief"]["mode"] == "full"
    assert any(edge["type"] == "uses_security_group" for edge in result["diagram_brief"]["selected_edges"])
    assert any(edge["type"] == "allows_egress_to" for edge in result["diagram_brief"]["selected_edges"])
    _assert_security_group_edges(result)
    _assert_subnet_and_service_summary(result)


@pytest.mark.asyncio
async def test_aws_topology_snapshot_returns_partial_policy_warnings(monkeypatch):
    async def fake_aws_json(context, service, command):
        if service == "sts":
            return {"Account": "123456789012"}
        if service == "ec2" and command[0] == "describe-vpcs":
            return {"Vpcs": []}
        if service == "ec2":
            return {}
        raise AssertionError(f"unexpected AWS call {service} {command}")

    monkeypatch.setattr(aws_topology_common, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_topology_snapshot",
        {"services": ["ec2", "rds"], "max_items": 5},
        aws_tool_context({"aws_region": "eu-central-1", "aws_allowed_services": ["sts", "ec2"]}),
    )

    assert "rds" in result["scope"]["services_skipped"]
    assert "rds" in result["service_summary"]["services_skipped"]
    assert result["service_summary"]["services_checked_no_resources"] == ["ec2"]
    assert any("not allowed" in warning["message"] for warning in result["warnings"])
    assert result["account_id"] == "123456789012"


@pytest.mark.asyncio
async def test_aws_topology_snapshot_enforces_node_limit(monkeypatch):
    async def fake_aws_json(context, service, command):
        if service == "sts":
            return {"Account": "123456789012"}
        if service == "ec2" and command[0] == "describe-vpcs":
            return {"Vpcs": [{"VpcId": f"vpc-{idx}"} for idx in range(5)]}
        if service == "ec2":
            return {}
        raise AssertionError(f"unexpected AWS call {service} {command}")

    monkeypatch.setattr(aws_topology_common, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_topology_snapshot",
        {"services": ["ec2"], "max_nodes": 2},
        aws_tool_context(),
    )

    assert len(result["nodes"]) == 2
    assert any(warning.get("reason") == "max_nodes" for warning in result["warnings"])
