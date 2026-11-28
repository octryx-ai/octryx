"""Tests for internal AWS Well-Architected assessment tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_well_architected
from app.tools.registry import execute_tool
from tests.tools.connectors.aws_tool_context_support import aws_tool_context


@pytest.mark.asyncio
async def test_well_architected_assessment_scores_pillars_from_supplied_evidence():
    result = await execute_tool(
        "aws_well_architected_assessment",
        {
            "topology_snapshot": {
                "scope": {"services_failed": [], "services_skipped": []},
                "nodes": [{"type": "eks_cluster"}],
            },
            "security_posture": {"summary": {"by_severity": {"critical": 1}}},
            "exposure_map": {"summary": {"high_severity_count": 1}},
            "cost_report": {"summary": {"unmapped_cost_count": 2}},
            "deployment_timeline": {"events": [{"status": "Failed"}]},
        },
        aws_tool_context(),
    )

    assert result["status"] == "ok"
    assert result["basis"] == "internal_derived_assessment_not_official_aws_well_architected_review"
    assert result["pillars"]["security"]["status"] == "risk"
    assert result["pillars"]["cost_optimization"]["status"] == "needs_review"
    assert result["pillars"]["reliability"]["status"] == "risk"


@pytest.mark.asyncio
async def test_well_architected_assessment_collects_missing_inputs(monkeypatch):
    async def fake_topology(context, params):
        return {"scope": {}, "nodes": [{"type": "lambda_function"}]}

    async def fake_security(context, params):
        return {"summary": {"by_severity": {}}}

    async def fake_exposure(context, params):
        return {"summary": {"high_severity_count": 0}}

    async def fake_cost(context, params):
        return {"summary": {"unmapped_cost_count": 0}}

    monkeypatch.setattr(aws_well_architected, "build_aws_topology_snapshot", fake_topology)
    monkeypatch.setattr(aws_well_architected, "build_aws_security_posture_summary", fake_security)
    monkeypatch.setattr(aws_well_architected, "build_aws_exposure_map", fake_exposure)
    monkeypatch.setattr(aws_well_architected, "build_aws_cost_topology_report", fake_cost)

    result = await execute_tool("aws_well_architected_assessment", {"collect_missing": True}, aws_tool_context())

    assert result["summary"]["check_count"] == 5
    assert result["pillars"]["performance_efficiency"]["status"] == "ok"


@pytest.mark.asyncio
async def test_well_architected_assessment_labels_internal_basis_on_checks():
    result = await execute_tool("aws_well_architected_assessment", {}, aws_tool_context())

    assert all(check["basis"] == "internal_derived_check_not_official_aws_review" for check in result["checks"])
    assert result["warnings"][0]["severity"] == "info"
