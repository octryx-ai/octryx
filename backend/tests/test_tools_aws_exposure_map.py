"""Tests for AWS exposure map tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_exposure_map
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _context(project_config=None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config=project_config or {"aws_region": "eu-central-1"},
    )


def _topology():
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "nodes": [
            {"id": "cidr:0.0.0.0/0", "type": "cidr", "label": "0.0.0.0/0", "service": "ec2"},
            {"id": "security_group:sg-1", "type": "security_group", "label": "app", "service": "ec2"},
            {
                "id": "load_balancer:lb-1",
                "type": "load_balancer",
                "label": "public-lb",
                "service": "elbv2",
                "attributes": {"scheme": "internet-facing"},
            },
            {
                "id": "rds:db-1",
                "type": "rds_instance",
                "label": "db-1",
                "service": "rds",
                "attributes": {"publicly_accessible": True},
            },
        ],
        "edges": [
            {
                "source": "cidr:0.0.0.0/0",
                "target": "security_group:sg-1",
                "type": "allows_ingress_to",
                "service": "ec2",
                "attributes": {"from_port": 443, "to_port": 443},
            }
        ],
    }


@pytest.mark.asyncio
async def test_exposure_map_returns_public_sources_edges_and_nodes():
    result = await execute_tool(
        "aws_exposure_map",
        {"topology_snapshot": _topology()},
        _context(),
    )

    exposed_ids = {item["node_id"] for item in result["exposed_nodes"]}
    assert result["status"] == "ok"
    assert result["summary"]["public_source_count"] == 1
    assert result["summary"]["public_ingress_edge_count"] == 1
    assert {"security_group:sg-1", "load_balancer:lb-1", "rds:db-1"}.issubset(exposed_ids)
    assert result["summary"]["high_severity_count"] == 1


@pytest.mark.asyncio
async def test_exposure_map_collects_topology_when_missing(monkeypatch):
    async def fake_snapshot_call(context, params):
        return _topology()

    monkeypatch.setattr(aws_exposure_map, "build_aws_topology_snapshot", fake_snapshot_call)

    result = await execute_tool("aws_exposure_map", {"snapshot_params": {"services": ["ec2"]}}, _context())

    assert result["topology_source"] == "collected"
    assert result["summary"]["exposed_node_count"] >= 1


@pytest.mark.asyncio
async def test_exposure_map_handles_private_topology():
    topology = {"nodes": [{"id": "vpc:vpc-1", "type": "vpc", "label": "vpc-1", "service": "ec2"}], "edges": []}

    result = await execute_tool("aws_exposure_map", {"topology_snapshot": topology}, _context())

    assert result["summary"]["exposed_node_count"] == 0
    assert result["exposure_edges"] == []
