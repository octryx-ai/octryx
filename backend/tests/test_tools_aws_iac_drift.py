"""Tests for AWS runtime versus IaC drift tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_iac_drift
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


def _snapshot(nodes, edges=None):
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "scope": {"services_succeeded": ["ec2", "rds"]},
        "nodes": nodes,
        "edges": edges or [],
    }


@pytest.mark.asyncio
async def test_runtime_vs_iac_drift_reports_missing_unmanaged_and_changed_resources():
    expected = _snapshot(
        [
            {
                "id": "vpc:vpc-1",
                "type": "vpc",
                "label": "vpc-1",
                "service": "ec2",
                "region": "eu-central-1",
                "attributes": {"cidr": "10.0.0.0/16"},
            },
            {
                "id": "rds:db-1",
                "type": "rds_instance",
                "label": "db-1",
                "service": "rds",
                "region": "eu-central-1",
                "attributes": {"engine": "postgres"},
            },
        ]
    )
    runtime = _snapshot(
        [
            {
                "id": "vpc:vpc-1",
                "type": "vpc",
                "label": "vpc-1",
                "service": "ec2",
                "region": "eu-central-1",
                "attributes": {"cidr": "10.1.0.0/16"},
            },
            {
                "id": "eks:cluster-1",
                "type": "eks_cluster",
                "label": "cluster-1",
                "service": "eks",
                "region": "eu-central-1",
            },
        ]
    )

    result = await execute_tool(
        "aws_runtime_vs_iac_drift",
        {"iac_snapshot": expected, "runtime_snapshot": runtime},
        _context(),
    )

    drift_kinds = {item["drift_kind"] for item in result["drift_items"]}
    assert result["status"] == "ok"
    assert {"configuration_drift", "missing_runtime", "unmanaged_runtime"}.issubset(drift_kinds)
    assert result["summary"]["total_drift_items"] == 3
    assert result["summary"]["has_high_severity"] is True


@pytest.mark.asyncio
async def test_runtime_vs_iac_drift_accepts_simple_iac_resources():
    result = await execute_tool(
        "aws_runtime_vs_iac_drift",
        {
            "iac_resources": [
                {
                    "type": "vpc",
                    "name": "vpc-1",
                    "service": "ec2",
                    "resource_id": "vpc-1",
                    "attributes": {"cidr": "10.0.0.0/16"},
                }
            ],
            "runtime_snapshot": _snapshot([]),
            "region": "eu-central-1",
        },
        _context(),
    )

    assert result["expected_source"] == "iac_resources"
    assert result["drift_items"][0]["drift_kind"] == "missing_runtime"
    assert result["drift_items"][0]["id"] == "vpc:vpc-1"


@pytest.mark.asyncio
async def test_runtime_vs_iac_drift_collects_runtime_when_missing(monkeypatch):
    async def fake_snapshot_call(context, params):
        return _snapshot(
            [
                {
                    "id": "vpc:vpc-2",
                    "type": "vpc",
                    "label": "vpc-2",
                    "service": "ec2",
                    "region": "eu-central-1",
                }
            ]
        )

    monkeypatch.setattr(aws_iac_drift, "build_aws_topology_snapshot", fake_snapshot_call)

    result = await execute_tool(
        "aws_runtime_vs_iac_drift",
        {"iac_snapshot": _snapshot([]), "snapshot_params": {"services": ["ec2"]}},
        _context(),
    )

    assert result["runtime_source"] == "collected"
    assert result["drift_items"][0]["drift_kind"] == "unmanaged_runtime"


@pytest.mark.asyncio
async def test_runtime_vs_iac_drift_requires_expected_source():
    result = await execute_tool("aws_runtime_vs_iac_drift", {"runtime_snapshot": _snapshot([])}, _context())

    assert result["status"] == "invalid_input"
    assert "required" in result["error"]
