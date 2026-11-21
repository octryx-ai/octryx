"""Tests for AWS cost topology report tool."""

from __future__ import annotations

import pytest

from app.tools.connectors import aws_core, aws_cost_topology
from app.tools.connectors.aws_core import _aws_json, _parse_cli_args
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


def _topology():
    return {
        "nodes": [
            {
                "id": "rds:db-1",
                "type": "rds_instance",
                "label": "db-1",
                "service": "rds",
                "evidence": [{"service": "rds", "operation": "describe-db-instances"}],
            },
            {"id": "eks:cluster-1", "type": "eks_cluster", "label": "cluster-1", "service": "eks"},
        ]
    }


def _service_cost_payload():
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
                "Groups": [
                    {
                        "Keys": ["Amazon Relational Database Service"],
                        "Metrics": {"UnblendedCost": {"Amount": "12.3456", "Unit": "USD"}},
                    },
                    {
                        "Keys": ["Unknown Enterprise Service"],
                        "Metrics": {"UnblendedCost": {"Amount": "3.00", "Unit": "USD"}},
                    },
                ],
            }
        ]
    }


def test_cost_explorer_metrics_parse_to_boto_param_name():
    operation, params = _parse_cli_args(["get-cost-and-usage", "--metrics", "UnblendedCost"])

    assert operation == "get-cost-and-usage"
    assert params["Metrics"] == "UnblendedCost"


@pytest.mark.asyncio
async def test_cost_explorer_metrics_are_sent_as_list(monkeypatch):
    calls = []

    class FakeClient:
        def get_cost_and_usage(self, **kwargs):
            calls.append(kwargs)
            return {"ResultsByTime": []}

    class FakeSession:
        def client(self, service):
            assert service == "ce"
            return FakeClient()

    async def fake_assume_role_if_needed(context, session):
        return session

    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: FakeSession())
    monkeypatch.setattr(aws_core, "_assume_role_if_needed", fake_assume_role_if_needed)

    await _aws_json(
        _context(),
        "ce",
        ["get-cost-and-usage", "--metrics", "UnblendedCost"],
    )

    assert calls[0]["Metrics"] == ["UnblendedCost"]


@pytest.mark.asyncio
async def test_cost_topology_report_maps_service_costs_to_topology(monkeypatch):
    calls = []

    async def fake_aws_json(context, service, command):
        calls.append((service, command))
        return _service_cost_payload()

    monkeypatch.setattr(aws_cost_topology, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_cost_topology_report",
        {"start": "2026-05-01", "end": "2026-06-01", "topology_snapshot": _topology()},
        _context(),
    )

    assert result["status"] == "ok"
    assert result["summary"]["total_amount"] == 15.3456
    assert result["summary"]["mapped_topology_allocation_count"] == 1
    assert result["topology_allocations"][0]["node_id"] == "rds:db-1"
    assert result["topology_allocations"][0]["allocation_basis"] == "service_level_not_resource_attributed"
    assert result["unmapped_costs"][0]["service_name"] == "Unknown Enterprise Service"
    assert calls[0][0] == "ce"
    assert "get-cost-and-usage" in calls[0][1]


@pytest.mark.asyncio
async def test_cost_topology_report_includes_tag_costs(monkeypatch):
    async def fake_aws_json(context, service, command):
        if "Type=TAG,Key=Environment" in command:
            return {
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": "2026-05-01", "End": "2026-06-01"},
                        "Groups": [
                            {
                                "Keys": ["Environment$prod"],
                                "Metrics": {"UnblendedCost": {"Amount": "8.00", "Unit": "USD"}},
                            }
                        ],
                    }
                ]
            }
        return _service_cost_payload()

    monkeypatch.setattr(aws_cost_topology, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_cost_topology_report",
        {
            "start": "2026-05-01",
            "end": "2026-06-01",
            "topology_snapshot": _topology(),
            "tag_keys": ["Environment"],
        },
        _context(),
    )

    assert result["tag_costs"][0]["tag_key"] == "Environment"
    assert result["tag_costs"][0]["values"][0]["amount"] == 8.0


@pytest.mark.asyncio
async def test_cost_topology_report_warns_without_topology(monkeypatch):
    async def fake_aws_json(context, service, command):
        return _service_cost_payload()

    monkeypatch.setattr(aws_cost_topology, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_cost_topology_report",
        {"start": "2026-05-01", "end": "2026-06-01"},
        _context(),
    )

    assert result["summary"]["mapped_topology_allocation_count"] == 0
    assert result["warnings"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_cost_topology_report_returns_controlled_error(monkeypatch):
    async def fake_aws_json(context, service, command):
        raise RuntimeError("Cost Explorer is not allowed")

    monkeypatch.setattr(aws_cost_topology, "_aws_json", fake_aws_json)

    result = await execute_tool(
        "aws_cost_topology_report",
        {"start": "2026-05-01", "end": "2026-06-01"},
        _context(),
    )

    assert result["status"] == "error"
    assert "Cost Explorer" in result["error"]
