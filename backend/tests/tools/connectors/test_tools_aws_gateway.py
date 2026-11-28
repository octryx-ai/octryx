"""Tests for controlled AWS CLI gateway tools."""

import json

import pytest

from app.tools.connectors import aws_gateway
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _context(project_config=None) -> ToolContext:
    # Connector tools are deny-by-default per project (tools/visibility.py): the
    # AWS connector must be activated before the gateway's own command policy
    # is even reached, which is what these tests exercise.
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config={"aws_enabled": True, **(project_config or {})},
    )


# aws_action_operation is a high-risk tool: the project tool policy must grant it
# by exact name before the gateway's own action allowlist is consulted.
_ACTION_TOOL_POLICY = {"tool_policy": {"high_risk_grants": ["aws_action_operation"]}}


@pytest.mark.asyncio
async def test_aws_read_operation_executes_safe_cli_command(monkeypatch):
    calls = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        calls.append((command, env, cwd))
        return 0, json.dumps({"clusters": ["demo-nonprod-eks"]}), ""

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_read_operation",
        {
            "service": "eks",
            "operation": "list-clusters",
            "arguments": {"region": "eu-central-1"},
        },
        _context(),
    )

    assert "error" not in result
    assert result["result"]["clusters"] == ["demo-nonprod-eks"]
    assert calls[0][0] == [
        "aws",
        "eks",
        "list-clusters",
        "--region",
        "eu-central-1",
        "--output",
        "json",
        "--no-cli-pager",
    ]
    assert calls[0][1]["AWS_PAGER"] == ""


@pytest.mark.asyncio
async def test_aws_read_operation_accepts_camel_case_api_operation(monkeypatch):
    calls = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        calls.append((command, env, cwd))
        return 0, json.dumps({"DBInstances": []}), ""

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_read_operation",
        {
            "service": "rds",
            "operation": "DescribeDBInstances",
            "arguments": {"region": "eu-central-1"},
        },
        _context(),
    )

    assert "error" not in result
    assert result["operation"] == "describe-db-instances"
    assert calls[0][0][:3] == ["aws", "rds", "describe-db-instances"]


@pytest.mark.asyncio
async def test_aws_read_operation_blocks_secret_value_reads(monkeypatch):
    async def fake_run_subprocess(command, *, env=None, cwd=None):
        raise AssertionError("AWS CLI should not be called")

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_read_operation",
        {"service": "secretsmanager", "operation": "get-secret-value", "arguments": {"secret_id": "prod/db"}},
        _context(),
    )

    assert result["error"] == "AWS operation is not allowed for read-only execution"


@pytest.mark.asyncio
async def test_aws_read_operation_blocks_forbidden_cli_global_argument(monkeypatch):
    async def fake_run_subprocess(command, *, env=None, cwd=None):
        raise AssertionError("AWS CLI should not be called")

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_read_operation",
        {"service": "eks", "operation": "list-clusters", "arguments": ["--profile=personal"]},
        _context(),
    )

    assert result["error"] == "AWS CLI argument '--profile=personal' is not allowed"


@pytest.mark.asyncio
async def test_aws_read_operation_respects_service_allowlist(monkeypatch):
    async def fake_run_subprocess(command, *, env=None, cwd=None):
        raise AssertionError("AWS CLI should not be called")

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_read_operation",
        {"service": "rds", "operation": "describe-db-clusters"},
        _context({"aws_allowed_services": ["eks"]}),
    )

    assert result["error"] == "AWS service 'rds' is not allowed"


@pytest.mark.asyncio
async def test_aws_action_operation_allows_codepipeline_with_policy(monkeypatch):
    calls = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        calls.append(command)
        return 0, json.dumps({"pipelineExecutionId": "exec-1"}), ""

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_action_operation",
        {
            "service": "codepipeline",
            "operation": "start-pipeline-execution",
            "arguments": {"name": "octryx-deploy"},
            "reason": "Deploy validated image",
        },
        _context(_ACTION_TOOL_POLICY),
    )

    assert result["result"]["pipelineExecutionId"] == "exec-1"
    assert calls[0][:5] == ["aws", "codepipeline", "start-pipeline-execution", "--name", "octryx-deploy"]


@pytest.mark.asyncio
async def test_aws_action_operation_blocks_unlisted_action(monkeypatch):
    async def fake_run_subprocess(command, *, env=None, cwd=None):
        raise AssertionError("AWS CLI should not be called")

    monkeypatch.setattr(aws_gateway, "_run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "aws_action_operation",
        {"service": "ec2", "operation": "stop-instances", "arguments": {"instance_ids": ["i-123"]}},
        _context(_ACTION_TOOL_POLICY),
    )

    assert result["error"] == "AWS action is not in the explicit action allowlist"
    assert "codepipeline:start-pipeline-execution" in result["allowed_actions"]
