"""Tests for AWS deployment timeline tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_deployment_timeline
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
async def test_deployment_timeline_lists_pipelines_when_missing(monkeypatch):
    calls = []

    async def fake_aws_json(context, service, command):
        calls.append((service, command))
        if command[0] == "list-pipelines":
            return {"pipelines": [{"name": "base_apply"}]}
        return {
            "pipelineExecutionSummaries": [
                {
                    "pipelineExecutionId": "exec-1",
                    "status": "Succeeded",
                    "startTime": "2026-05-31T10:00:00+00:00",
                    "lastUpdateTime": "2026-05-31T10:10:00+00:00",
                }
            ]
        }

    monkeypatch.setattr(aws_deployment_timeline, "_aws_json", fake_aws_json)

    result = await execute_tool("aws_deployment_timeline", {}, _context())

    assert result["status"] == "ok"
    assert result["pipeline_names"] == ["base_apply"]
    assert result["events"][0]["execution_id"] == "exec-1"
    assert calls[0][1] == ["list-pipelines"]


@pytest.mark.asyncio
async def test_deployment_timeline_orders_events_and_marks_failed(monkeypatch):
    async def fake_aws_json(context, service, command):
        return {
            "pipelineExecutionSummaries": [
                {
                    "pipelineExecutionId": "old",
                    "status": "Succeeded",
                    "startTime": "2026-05-30T10:00:00+00:00",
                },
                {
                    "pipelineExecutionId": "new",
                    "status": "Failed",
                    "startTime": "2026-05-31T10:00:00+00:00",
                },
            ]
        }

    monkeypatch.setattr(aws_deployment_timeline, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_deployment_timeline",
        {"pipeline_names": ["base_apply"], "max_executions_per_pipeline": 5},
        _context(),
    )

    assert [event["execution_id"] for event in result["events"]] == ["new", "old"]
    assert result["events"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_deployment_timeline_returns_source_warnings(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise RuntimeError("codepipeline denied")

    monkeypatch.setattr(aws_deployment_timeline, "_aws_json", fake_aws_json)

    result = await execute_tool("aws_deployment_timeline", {"pipeline_names": ["base_apply"]}, _context())

    assert result["events"] == []
    assert result["summary"]["warning_count"] == 1
    assert "denied" in result["warnings"][0]["message"]
