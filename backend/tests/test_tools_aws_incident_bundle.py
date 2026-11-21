"""Tests for AWS incident evidence bundle tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_incident_bundle
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


@pytest.mark.asyncio
async def test_incident_evidence_bundle_packages_sections_and_redacts_sensitive_keys():
    result = await execute_tool(
        "aws_incident_evidence_bundle",
        {
            "incident_id": "INC-1",
            "title": "WAF investigation",
            "severity": "high",
            "topology_snapshot": {"nodes": [{"id": "waf:waf-1", "evidence": [{"service": "wafv2"}]}]},
            "additional_evidence": [{"authorization": "Bearer secret", "message": "safe"}],
        },
        _context(),
    )

    assert result["status"] == "ok"
    assert result["incident"]["id"] == "INC-1"
    assert result["summary"]["section_count"] == 2
    assert result["summary"]["redaction_count"] == 1
    additional = next(section for section in result["sections"] if section["name"] == "additional_evidence")
    assert additional["payload"][0]["authorization"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_incident_evidence_bundle_collects_missing_sections(monkeypatch):
    async def fake_topology(context, params):
        return {"nodes": [{"id": "vpc:vpc-1"}], "edges": []}

    async def fake_security(context, params):
        return {"summary": {"finding_count": 0}, "findings": []}

    async def fake_exposure(context, params):
        return {"summary": {"exposed_node_count": 0}, "exposed_nodes": []}

    async def fake_timeline(context, params):
        return {"summary": {"event_count": 1}, "events": [{"evidence": [{"service": "codepipeline"}]}]}

    monkeypatch.setattr(aws_incident_bundle, "build_aws_topology_snapshot", fake_topology)
    monkeypatch.setattr(aws_incident_bundle, "build_aws_security_posture_summary", fake_security)
    monkeypatch.setattr(aws_incident_bundle, "build_aws_exposure_map", fake_exposure)
    monkeypatch.setattr(aws_incident_bundle, "build_aws_deployment_timeline", fake_timeline)

    result = await execute_tool(
        "aws_incident_evidence_bundle",
        {"collect_missing": True, "timeline_params": {"pipeline_names": ["base_apply"]}},
        _context(),
    )

    section_names = {section["name"] for section in result["sections"]}
    assert {"topology", "security_posture", "exposure_map", "deployment_timeline"}.issubset(section_names)
    assert result["summary"]["collect_missing"] is True


@pytest.mark.asyncio
async def test_incident_evidence_bundle_keeps_empty_sections_out():
    result = await execute_tool(
        "aws_incident_evidence_bundle",
        {"title": "Empty bundle"},
        _context(),
    )

    assert result["summary"]["section_count"] == 0
    assert result["sections"] == []
