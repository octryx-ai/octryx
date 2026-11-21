"""Tests for controlled AWS Config query tool."""

from __future__ import annotations

import json

import pytest

from app.tools.connectors import aws_config_query
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
async def test_aws_config_query_template_parses_results_and_evidence(monkeypatch):
    calls = []

    async def fake_aws_json(context, service, command):
        calls.append((service, command))
        return {
            "Results": [
                json.dumps(
                    {
                        "resourceType": "AWS::EC2::VPC",
                        "resourceId": "vpc-1",
                        "awsRegion": "eu-central-1",
                    }
                )
            ],
            "NextToken": "token-2",
        }

    monkeypatch.setattr(aws_config_query, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_config_query",
        {"template": "ec2_network_inventory", "limit": 10, "next_token": "token-1"},
        _context(),
    )

    assert result["status"] == "ok"
    assert result["items"][0]["resourceId"] == "vpc-1"
    assert result["evidence"][0]["service"] == "configservice"
    assert result["next_token"] == "token-2"
    assert calls[0][0] == "configservice"
    assert calls[0][1][:5] == [
        "select-resource-config",
        "--expression",
        aws_config_query.QUERY_TEMPLATES["ec2_network_inventory"],
        "--limit",
        "10",
    ]
    assert calls[0][1][-2:] == ["--next-token", "token-1"]


@pytest.mark.asyncio
async def test_aws_config_query_validates_custom_select(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise AssertionError("AWS Config should not be called for invalid custom query")

    monkeypatch.setattr(aws_config_query, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_config_query",
        {"query": "SELECT resourceId; DELETE FROM resources"},
        _context(),
    )

    assert result["status"] == "invalid_query"
    assert "statement separators" in result["error"]


@pytest.mark.asyncio
async def test_aws_config_query_respects_service_allowlist(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise AssertionError("AWS Config should not be called when the service is blocked")

    monkeypatch.setattr(aws_config_query, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_config_query",
        {"template": "resource_inventory"},
        _context({"aws_region": "eu-central-1", "aws_allowed_services": ["sts", "ec2"]}),
    )

    assert result["status"] == "blocked"
    assert result["items"] == []
    assert "not allowed" in result["error"]


@pytest.mark.asyncio
async def test_aws_config_query_returns_error_status_for_disabled_config(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise RuntimeError("Configuration recorder is not available")

    monkeypatch.setattr(aws_config_query, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_config_query",
        {"template": "resource_inventory"},
        _context(),
    )

    assert result["status"] == "error"
    assert result["items"] == []
    assert "Configuration recorder" in result["warnings"][0]["message"]
