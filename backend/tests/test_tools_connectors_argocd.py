"""Connector tools and the native connection health check for Argo CD."""

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_argocd_tools_cover_status_sync_rollback_and_events(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert headers["Authorization"] == "Bearer argocd-token"
        if method == "GET" and url == "https://argocd.example.com/api/v1/applications":
            return {
                "items": [
                    {
                        "metadata": {"name": "acme-orders-api"},
                        "spec": {
                            "project": "default",
                            "source": {
                                "repoURL": "https://git.example/repo",
                                "targetRevision": "main",
                                "path": "charts/api",
                            },
                        },
                        "status": {
                            "sync": {"status": "Synced", "revision": "abc"},
                            "health": {"status": "Healthy"},
                            "history": [],
                        },
                    }
                ]
            }
        if method == "GET" and url == "https://argocd.example.com/api/v1/applications/acme-orders-api":
            return {
                "metadata": {"name": "acme-orders-api"},
                "spec": {
                    "project": "default",
                    "source": {"repoURL": "https://git.example/repo", "targetRevision": "main", "path": "charts/api"},
                },
                "status": {
                    "sync": {"status": "Synced", "revision": "abc"},
                    "health": {"status": "Healthy"},
                    "operationState": {"phase": "Succeeded", "message": "sync completed"},
                    "history": [{"id": 3, "revision": "abc"}],
                },
            }
        if method == "POST" and url == "https://argocd.example.com/api/v1/applications/acme-orders-api/sync":
            return {"status": "sync started"}
        if method == "POST" and url == "https://argocd.example.com/api/v1/applications/acme-orders-api/rollback":
            assert json_body["id"] == 3
            return {"status": "rollback started"}
        if method == "GET" and url == "https://argocd.example.com/api/v1/applications/acme-orders-api/events":
            return {
                "items": [
                    {
                        "reason": "Synced",
                        "message": "Application synced",
                        "type": "Normal",
                        "lastTimestamp": "2026-03-28T00:00:00Z",
                    }
                ]
            }
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "tool_policy": {"high_risk_grants": ["sync_app", "rollback_app"]},
            "argocd_url": "https://argocd.example.com",
            "argocd_token": "argocd-token",
            "argocd_allowed_applications": ["acme-orders-api"],
        },
    )

    apps = await execute_tool("list_apps", {}, context)
    assert apps["count"] == 1
    assert apps["applications"][0]["name"] == "acme-orders-api"

    status = await execute_tool("get_app_status", {}, context)
    assert status["application"]["sync_status"] == "Synced"

    sync = await execute_tool("sync_app", {}, context)
    assert sync["status"] == "sync_started"

    rollout = await execute_tool("get_rollout_status", {}, context)
    assert rollout["operation_phase"] == "Succeeded"

    rollback = await execute_tool("rollback_app", {"history_id": 3}, context)
    assert rollback["status"] == "rollback_started"

    events = await execute_tool("list_events", {}, context)
    assert events["count"] == 1
    assert events["events"][0]["reason"] == "Synced"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_argocd_connector_health_supports_native_connection_test(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            import httpx

            request = httpx.Request("GET", url)
            if url.endswith("/api/v1/session/userinfo"):
                return httpx.Response(200, json={"loggedIn": True, "username": "argocd-admin"}, request=request)
            raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    result = await run_connector_connection_test(
        "argocd",
        {"argocd_url": "https://argocd.example.com", "argocd_token": "argocd-token"},
    )
    assert result["ok"] is True
    assert "ArgoCD" in result["summary"]
