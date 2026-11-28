"""Tests for AWS security posture summary tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_security_posture
from app.tools.registry import execute_tool
from tests.tools.connectors.aws_tool_context_support import aws_tool_context


def _topology():
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "scope": {"services_failed": ["guardduty"], "services_skipped": ["inspector2"]},
        "nodes": [
            {
                "id": "cidr:0.0.0.0/0",
                "type": "cidr",
                "label": "0.0.0.0/0",
                "service": "ec2",
                "evidence": [{"service": "ec2", "operation": "describe-security-groups"}],
            },
            {
                "id": "security_group:sg-1",
                "type": "security_group",
                "label": "app",
                "service": "ec2",
                "evidence": [{"service": "ec2", "operation": "describe-security-groups"}],
            },
            {
                "id": "load_balancer:lb-1",
                "type": "load_balancer",
                "label": "public-lb",
                "service": "elbv2",
                "tags": {},
                "attributes": {"scheme": "internet-facing", "dns_name": "public.example"},
            },
            {"id": "rds:db-1", "type": "rds_instance", "label": "db-1", "service": "rds", "tags": {}},
        ],
        "edges": [
            {
                "source": "cidr:0.0.0.0/0",
                "target": "security_group:sg-1",
                "type": "allows_ingress_to",
                "service": "ec2",
                "attributes": {"protocol": "tcp", "from_port": 22, "to_port": 22},
                "evidence": [{"service": "ec2", "operation": "describe-security-groups"}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_security_posture_summary_derives_findings_from_topology():
    result = await execute_tool(
        "aws_security_posture_summary",
        {"topology_snapshot": _topology()},
        aws_tool_context(),
    )

    categories = {finding["category"] for finding in result["findings"]}
    assert result["status"] == "ok"
    assert {"public_ingress", "public_endpoint", "tag_governance", "coverage_gap"}.issubset(categories)
    assert result["summary"]["by_severity"]["critical"] == 1
    assert result["summary"]["has_critical"] is True


@pytest.mark.asyncio
async def test_security_posture_summary_collects_topology_when_missing(monkeypatch):
    async def fake_snapshot_call(context, params):
        return _topology()

    monkeypatch.setattr(aws_security_posture, "build_aws_topology_snapshot", fake_snapshot_call)

    result = await execute_tool(
        "aws_security_posture_summary",
        {"snapshot_params": {"services": ["ec2"]}},
        aws_tool_context(),
    )

    assert result["topology_source"] == "collected"
    assert result["summary"]["finding_count"] >= 1


@pytest.mark.asyncio
async def test_security_posture_summary_ignores_non_public_ingress():
    topology = _topology()
    topology["nodes"][0]["label"] = "10.0.0.0/8"

    result = await execute_tool(
        "aws_security_posture_summary",
        {"topology_snapshot": topology},
        aws_tool_context(),
    )

    assert "public_ingress" not in {finding["category"] for finding in result["findings"]}
