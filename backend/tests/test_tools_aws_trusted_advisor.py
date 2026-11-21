"""Tests for AWS Trusted Advisor summary tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_trusted_advisor
from app.tools.connectors.aws_core import _parse_cli_args
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


def test_trusted_advisor_core_params_need_lowercase_language():
    operation, params = _parse_cli_args(["describe-trusted-advisor-checks", "--language", "en"])

    lowered = {key[0].lower() + key[1:]: value for key, value in params.items()}
    assert operation == "describe-trusted-advisor-checks"
    assert lowered == {"language": "en"}


@pytest.mark.asyncio
async def test_trusted_advisor_summary_lists_checks(monkeypatch):
    async def fake_aws_json(context, service, command):
        assert service == "support"
        assert command[0] == "describe-trusted-advisor-checks"
        return {
            "checks": [
                {
                    "id": "check-1",
                    "name": "Low Utilization Amazon EC2 Instances",
                    "category": "cost_optimizing",
                    "description": "Checks EC2 utilization.",
                    "metadata": ["Region", "Instance ID"],
                }
            ]
        }

    monkeypatch.setattr(aws_trusted_advisor, "_aws_json", fake_aws_json)

    result = await execute_tool("aws_trusted_advisor_summary", {}, _context())

    assert result["status"] == "ok"
    assert result["summary"]["check_count"] == 1
    assert result["summary"]["checks_by_category"]["cost_optimizing"] == 1
    assert result["checks"][0]["evidence"][0]["service"] == "support"


@pytest.mark.asyncio
async def test_trusted_advisor_summary_fetches_requested_results(monkeypatch):
    async def fake_aws_json(context, service, command):
        if command[0] == "describe-trusted-advisor-checks":
            return {"checks": [{"id": "check-1", "name": "MFA", "category": "security"}]}
        return {
            "result": {
                "status": "warning",
                "timestamp": "2026-05-31T10:00:00Z",
                "resourcesSummary": {"resourcesFlagged": 2},
                "flaggedResources": [{"resourceId": "user-1"}, {"resourceId": "user-2"}],
            }
        }

    monkeypatch.setattr(aws_trusted_advisor, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_trusted_advisor_summary",
        {"check_ids": ["check-1"]},
        _context(),
    )

    assert result["summary"]["result_count"] == 1
    assert result["check_results"][0]["flagged_resource_count"] == 2
    assert result["check_results"][0]["status"] == "warning"


@pytest.mark.asyncio
async def test_trusted_advisor_summary_returns_unavailable_warning(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise RuntimeError("SubscriptionRequiredException")

    monkeypatch.setattr(aws_trusted_advisor, "_aws_json", fake_aws_json)

    result = await execute_tool("aws_trusted_advisor_summary", {}, _context())

    assert result["status"] == "unavailable"
    assert result["checks"] == []
    assert "SubscriptionRequiredException" in result["warnings"][0]["message"]
