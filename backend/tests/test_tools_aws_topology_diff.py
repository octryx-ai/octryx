"""Tests for AWS topology diff tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_topology_diff
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


def _snapshot(*, nodes, edges=None, services=None, account_id="123456789012", region="eu-central-1"):
    return {
        "account_id": account_id,
        "region": region,
        "generated_at": "2026-05-31T20:00:00+00:00",
        "scope": {"services_succeeded": services or ["ec2"]},
        "nodes": nodes,
        "edges": edges or [],
    }


@pytest.mark.asyncio
async def test_aws_topology_diff_reports_added_removed_and_changed_nodes():
    baseline = _snapshot(
        nodes=[
            {
                "id": "vpc:vpc-1",
                "type": "vpc",
                "label": "vpc-1",
                "service": "ec2",
                "region": "eu-central-1",
                "attributes": {"state": "available"},
                "evidence": [{"service": "ec2", "operation": "describe-vpcs"}],
            },
            {
                "id": "rds:db-1",
                "type": "rds_instance",
                "label": "db-1",
                "service": "rds",
                "region": "eu-central-1",
                "attributes": {"engine": "postgres"},
            },
        ],
    )
    candidate = _snapshot(
        nodes=[
            {
                "id": "vpc:vpc-1",
                "type": "vpc",
                "label": "vpc-prod",
                "service": "ec2",
                "region": "eu-central-1",
                "attributes": {"state": "available"},
                "evidence": [{"service": "ec2", "operation": "describe-vpcs"}],
            },
            {
                "id": "eks:cluster-1",
                "type": "eks_cluster",
                "label": "cluster-1",
                "service": "eks",
                "region": "eu-central-1",
                "attributes": {"status": "ACTIVE"},
            },
        ],
        services=["ec2", "eks"],
    )

    result = await execute_tool(
        "aws_topology_diff",
        {"baseline_snapshot": baseline, "candidate_snapshot": candidate},
        _context(),
    )

    change_types = {(diff["id"], diff["change_type"]) for diff in result["node_diffs"]}
    assert result["status"] == "ok"
    assert ("eks:cluster-1", "added") in change_types
    assert ("rds:db-1", "removed") in change_types
    assert ("vpc:vpc-1", "changed") in change_types
    assert result["summary"]["nodes_added"] == 1
    assert result["summary"]["nodes_removed"] == 1
    assert result["summary"]["nodes_changed"] == 1
    assert result["service_summary"]["eks"]["added"] == 1
    assert any(warning["reason"] == "service_coverage_mismatch" for warning in result["warnings"])


@pytest.mark.asyncio
async def test_aws_topology_diff_does_not_call_aws_when_snapshots_are_supplied(monkeypatch):
    async def fail_snapshot_call(context, params):
        raise AssertionError("candidate snapshot should not be collected when supplied")

    monkeypatch.setattr(aws_topology_diff, "build_aws_topology_snapshot", fail_snapshot_call)
    baseline = _snapshot(nodes=[])
    candidate = _snapshot(nodes=[])

    result = await execute_tool(
        "aws_topology_diff",
        {"baseline_snapshot": baseline, "candidate_snapshot": candidate},
        _context(),
    )

    assert result["summary"]["nodes_added"] == 0
    assert result["summary"]["edges_added"] == 0


@pytest.mark.asyncio
async def test_aws_topology_diff_collects_candidate_when_missing(monkeypatch):
    async def fake_snapshot_call(context, params):
        return _snapshot(
            nodes=[
                {
                    "id": "vpc:vpc-2",
                    "type": "vpc",
                    "label": "vpc-2",
                    "service": "ec2",
                    "region": "eu-central-1",
                }
            ]
        )

    monkeypatch.setattr(aws_topology_diff, "build_aws_topology_snapshot", fake_snapshot_call)

    result = await execute_tool(
        "aws_topology_diff",
        {"baseline_snapshot": _snapshot(nodes=[]), "snapshot_params": {"services": ["ec2"]}},
        _context(),
    )

    assert result["summary"]["nodes_added"] == 1
    assert result["node_diffs"][0]["id"] == "vpc:vpc-2"


@pytest.mark.asyncio
async def test_aws_topology_diff_warns_on_scope_mismatch():
    baseline = _snapshot(nodes=[], account_id="111111111111", region="eu-central-1")
    candidate = _snapshot(nodes=[], account_id="222222222222", region="us-east-1")

    result = await execute_tool(
        "aws_topology_diff",
        {"baseline_snapshot": baseline, "candidate_snapshot": candidate},
        _context(),
    )

    reasons = {warning["reason"] for warning in result["warnings"]}
    assert {"account_id_mismatch", "region_mismatch"}.issubset(reasons)
