"""Helm connector tools for release inspection, dry runs and approval, and its native connection test."""

import json

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool

HELM_LIST_RELEASES_PAYLOAD = [
    {
        "name": "acme-orders-api",
        "namespace": "acme-orders",
        "revision": "7",
        "status": "deployed",
        "chart": "acme-orders-api-0.1.0",
        "app_version": "1.0.0",
        "updated": "2026-03-28 09:00:00",
    }
]


HELM_STATUS_PAYLOAD = {
    "name": "acme-orders-api",
    "namespace": "acme-orders",
    "version": 7,
    "info": {"status": "deployed", "description": "Install complete"},
    "chart": {"metadata": {"name": "acme-orders-api", "appVersion": "1.0.0"}},
}


HELM_HISTORY_PAYLOAD = [
    {
        "revision": 7,
        "status": "deployed",
        "chart": "acme-orders-api-0.1.0",
        "description": "Install complete",
    }
]


def _helm_tool_context(tmp_path, chart_dir) -> ToolContext:
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="helm-session",
        workspace_root=str(tmp_path),
        project_config={
            "tool_policy": {"high_risk_grants": ["upgrade", "rollback"]},
            "helm_binary": "helm",
            "helm_workspace_root": str(tmp_path),
            "helm_namespace": "acme-orders",
            "helm_allowed_namespaces": ["acme-orders"],
            "helm_allowed_releases": ["acme-orders-api"],
            "helm_allowed_charts": [str(chart_dir)],
            "helm_chart": str(chart_dir),
        },
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_helm_tools_cover_release_inspection_dry_run_and_approval(monkeypatch, tmp_path):
    chart_dir = tmp_path / "charts" / "acme-orders-api"
    chart_dir.mkdir(parents=True)

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        rendered = " ".join(command)
        assert cwd == str(tmp_path)
        if command[1:4] == ["list", "-o", "json"]:
            return 0, json.dumps(HELM_LIST_RELEASES_PAYLOAD), ""
        if command[1:5] == ["status", "acme-orders-api", "-o", "json"]:
            return 0, json.dumps(HELM_STATUS_PAYLOAD), ""
        if command[1:5] == ["history", "acme-orders-api", "-o", "json"]:
            return 0, json.dumps(HELM_HISTORY_PAYLOAD), ""
        if "--dry-run" in command:
            return 0, "DRY RUN OK", ""
        if command[1] == "upgrade":
            return 0, "UPGRADE OK", ""
        if command[1] == "rollback":
            return 0, "ROLLBACK OK", ""
        raise AssertionError(f"unexpected command {rendered}")

    monkeypatch.setattr("app.tools.connectors.helm_runtime._run_subprocess", fake_run_subprocess)
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    context = _helm_tool_context(tmp_path, chart_dir)

    listed = await execute_tool("list_releases", {}, context)
    assert listed["count"] == 1
    assert listed["releases"][0]["name"] == "acme-orders-api"

    status = await execute_tool("get_status", {"release_name": "acme-orders-api"}, context)
    assert status["release"]["status"] == "deployed"

    history = await execute_tool("get_history", {"release_name": "acme-orders-api"}, context)
    assert history["history"][0]["revision"] == 7

    dry_run = await execute_tool(
        "upgrade", {"release_name": "acme-orders-api", "chart": str(chart_dir), "dry_run": True}, context
    )
    assert dry_run["status"] == "dry_run_completed"

    upgraded = await execute_tool("upgrade", {"release_name": "acme-orders-api", "chart": str(chart_dir)}, context)
    assert upgraded["status"] == "completed"

    rolled_back = await execute_tool("rollback", {"release_name": "acme-orders-api", "revision": "6"}, context)
    assert rolled_back["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_helm_connector_health_supports_native_test(monkeypatch, tmp_path):
    helm_binary = tmp_path / "helm"
    helm_binary.write_text("#!/bin/sh\nprintf 'v3.15.1+gtest\\n'\n", encoding="utf-8")
    helm_binary.chmod(0o755)

    result = await run_connector_connection_test(
        "helm",
        {
            "helm_binary": str(helm_binary),
            "helm_workspace_root": ".",
        },
    )
    assert result["ok"] is True
    assert "Helm" in result["summary"]
