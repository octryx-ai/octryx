"""Tests for AWS network path analyzer tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_network_path
from app.tools.registry import execute_tool
from tests.tools.connectors.aws_tool_context_support import aws_tool_context


def _topology():
    return {
        "nodes": [
            {"id": "cidr:0.0.0.0/0", "type": "cidr", "label": "0.0.0.0/0", "service": "ec2"},
            {"id": "security_group:sg-1", "type": "security_group", "label": "app", "service": "ec2"},
            {"id": "rds:db-1", "type": "rds_instance", "label": "db-1", "service": "rds"},
            {"id": "vpc:vpc-1", "type": "vpc", "label": "vpc-1", "service": "ec2"},
        ],
        "edges": [
            {
                "source": "cidr:0.0.0.0/0",
                "target": "security_group:sg-1",
                "type": "allows_ingress_to",
                "service": "ec2",
                "attributes": {"from_port": 5432, "to_port": 5432, "protocol": "tcp"},
            },
            {
                "source": "rds:db-1",
                "target": "security_group:sg-1",
                "type": "uses_security_group",
                "service": "rds",
            },
        ],
    }


@pytest.mark.asyncio
async def test_network_path_analyzer_finds_static_relationship_path():
    result = await execute_tool(
        "aws_network_path_analyzer",
        {
            "topology_snapshot": _topology(),
            "source_node_id": "cidr:0.0.0.0/0",
            "target_node_id": "rds:db-1",
        },
        aws_tool_context(),
    )

    assert result["status"] == "ok"
    assert result["reachability"] == "path_found"
    assert result["paths"][0]["hop_count"] == 2
    assert result["paths"][0]["hops"][1]["via_edge"]["type"] == "allows_ingress_to"
    assert result["exposure_notes"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_network_path_analyzer_returns_no_static_path_when_disconnected():
    result = await execute_tool(
        "aws_network_path_analyzer",
        {
            "topology_snapshot": _topology(),
            "source_node_id": "cidr:0.0.0.0/0",
            "target_node_id": "vpc:vpc-1",
        },
        aws_tool_context(),
    )

    assert result["reachability"] == "no_static_path_found"
    assert result["paths"] == []


@pytest.mark.asyncio
async def test_network_path_analyzer_collects_topology_when_missing(monkeypatch):
    async def fake_snapshot_call(context, params):
        return _topology()

    monkeypatch.setattr(aws_network_path, "build_aws_topology_snapshot", fake_snapshot_call)

    result = await execute_tool(
        "aws_network_path_analyzer",
        {"source_label": "0.0.0.0/0", "target_label": "db-1"},
        aws_tool_context(),
    )

    assert result["topology_source"] == "collected"
    assert result["target_node_id"] == "rds:db-1"


@pytest.mark.asyncio
async def test_network_path_analyzer_requires_resolved_nodes():
    result = await execute_tool(
        "aws_network_path_analyzer",
        {"topology_snapshot": _topology(), "source_node_id": "missing", "target_node_id": "rds:db-1"},
        aws_tool_context(),
    )

    assert result["status"] == "invalid_input"
