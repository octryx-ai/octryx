"""Vault tools for read, list, renew, revoke and audit and the native Vault connection test."""

import pytest

from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_vault_tools_cover_read_list_renew_revoke_and_audit(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert headers["X-Vault-Token"] == "vault-token"
        assert headers["X-Vault-Namespace"] == "platform"
        if method == "GET" and url == "https://vault.example.com/v1/secret/data/apps/acme-orders":
            assert params == {"version": 2}
            return {
                "lease_id": "lease-1",
                "renewable": True,
                "data": {
                    "data": {"username": "svc-acme-orders", "password": "redacted"},
                    "metadata": {"version": 2},
                },
            }
        if method == "LIST" and url == "https://vault.example.com/v1/secret/metadata/apps/acme-orders":
            return {"data": {"keys": ["db", "redis"]}}
        if method == "PUT" and url == "https://vault.example.com/v1/sys/leases/renew":
            assert json_body == {"lease_id": "lease-1", "increment": 600}
            return {"lease_id": "lease-1", "renewable": True, "lease_duration": 3600}
        if method == "POST" and url == "https://vault.example.com/v1/auth/token/revoke":
            assert json_body == {"token": "child-token"}
            return {}
        if method == "GET" and url == "https://vault.example.com/v1/sys/audit":
            return {"data": {"file/": {"type": "file", "description": "audit sink"}}}
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "vault_url": "https://vault.example.com",
            "vault_token": "vault-token",
            "vault_namespace": "platform",
            "vault_kv_mount": "secret",
            "vault_allowed_paths": ["apps/acme-orders"],
            "vault_audit_path": "sys/audit",
            "tool_policy": {"high_risk_grants": ["renew_lease", "revoke_token"]},
        },
    )

    secret = await execute_tool("read_secret", {"path": "apps/acme-orders", "version": 2}, context)
    assert secret["secret"]["username"] == "svc-acme-orders"
    assert secret["metadata"]["version"] == 2

    keys = await execute_tool("list_secrets", {"path": "apps/acme-orders"}, context)
    assert keys["keys"] == ["db", "redis"]

    renewed = await execute_tool("renew_lease", {"lease_id": "lease-1", "increment_seconds": 600}, context)
    assert renewed["lease_duration"] == 3600

    revoked = await execute_tool("revoke_token", {"token": "child-token"}, context)
    assert revoked["status"] == "revoked"

    audit = await execute_tool("audit_log_read", {}, context)
    assert audit["count"] == 1

    denied = await execute_tool("read_secret", {"path": "shared/forbidden"}, context)
    assert denied["error"] == "path is not allowed by Vault policy"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_vault_connector_health_supports_native_connection_test(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"data": {"display_name": "token-app"}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            assert url == "https://vault.example.com/v1/auth/token/lookup-self"
            assert headers["X-Vault-Token"] == "vault-token"
            assert headers["X-Vault-Namespace"] == "platform"
            return FakeResponse()

    monkeypatch.setattr(connector_test_service_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await run_connector_connection_test(
        "vault",
        {
            "vault_url": "https://vault.example.com",
            "vault_token": "vault-token",
            "vault_namespace": "platform",
            "vault_kv_mount": "secret",
        },
    )

    assert result["ok"] is True
    assert result["summary"] == "Connected to Vault."
    assert "token-app" not in str(result)
