"""The admin tools connection test for Jira, Kubernetes, Bitbucket and Confluence, and a failure as a fixed result without the error text."""

import pytest

from app.services import connector_test_service
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_admin_tools_can_test_jira_connection(client, db, monkeypatch):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    async def fake_test(config):
        assert config["jira_url"] == "https://company.atlassian.net"
        assert config["jira_token"] == "secret"
        return {"ok": True, "summary": "Connected to Jira (REST API 3).", "details": None}

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "jira", fake_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "jira",
            "project_id": "",
            "description": "Jira cloud access",
            "config_json": '{"jira_url": "https://company.atlassian.net", "jira_auth_mode": "cloud_api_token", '
            '"jira_email": "admin@example.com"}',
            "jira_token": "secret",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "Connected to Jira (REST API 3)." in resp.text


@pytest.mark.asyncio
async def test_admin_tools_connection_test_failure_is_a_fixed_result_without_the_error_text(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    async def failing_test(config):
        raise ConnectionError("cannot reach https://internal-host.example.test:8443/rest/api/3/myself")

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "jira", failing_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "jira",
            "project_id": "",
            "description": "Jira cloud access",
            "config_json": '{"jira_url": "https://company.atlassian.net", "jira_auth_mode": "cloud_api_token", '
            '"jira_email": "admin@example.com"}',
            "jira_token": "secret",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "jira connection test failed." in resp.text
    assert "error_type=ConnectionError" in resp.text
    assert "internal-host.example.test" not in resp.text


@pytest.mark.asyncio
async def test_admin_tools_can_test_jira_connection_with_username_password(client, db, monkeypatch):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    async def fake_test(config):
        assert config["jira_username"] == "alice"
        assert config["jira_password"] == "secret"
        return {"ok": True, "summary": "Connected to Jira (REST API 2).", "details": None}

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "jira", fake_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "jira",
            "project_id": "",
            "description": "Jira server access",
            "config_json": '{"jira_url": "https://jira.example.test/jira", "jira_auth_mode": "basic", "jira_username": "alice"}',
            "jira_password": "secret",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "Connected to Jira (REST API 2)." in resp.text


@pytest.mark.asyncio
async def test_admin_tools_can_test_kubernetes_connection(client, db, monkeypatch):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    # Kubernetes is a SESSION_CONNECTOR_TESTS entry: its test is called with the request's ``db`` too.
    async def fake_test(config, *, db=None):
        assert config["k8s_context"] == "demo-cluster"
        assert db is not None
        return {"ok": True, "summary": "kubectl connection succeeded.", "details": "version=1.29.3."}

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "kubernetes", fake_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "kubernetes",
            "project_id": "",
            "description": "Demo cluster",
            "config_json": '{"k8s_use_kubectl": true, "k8s_context": "demo-cluster", "k8s_namespace": "default"}',
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "kubectl connection succeeded." in resp.text
    assert "version=1.29.3." in resp.text


@pytest.mark.asyncio
async def test_admin_tools_can_test_bitbucket_connection(client, db, monkeypatch):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    async def fake_test(config):
        assert config["bitbucket_url"] == "https://scm.example.test/bitbucket"
        assert config["bitbucket_password"] == "secret"
        return {"ok": True, "summary": "Connected to Bitbucket.", "details": "version=9.1.0."}

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "bitbucket", fake_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "bitbucket",
            "project_id": "",
            "description": "Bitbucket access",
            "config_json": '{"bitbucket_url": "https://scm.example.test/bitbucket", "bitbucket_auth_mode": "basic", "bitbucket_username": "alice", "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": true}]}',
            "bitbucket_password": "secret",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "Connected to Bitbucket." in resp.text
    assert "version=9.1.0." in resp.text


@pytest.mark.asyncio
async def test_admin_tools_can_test_confluence_connection(client, db, monkeypatch):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    async def fake_test(config):
        assert config["confluence_url"] == "https://wiki.example.com/wiki"
        assert config["confluence_password"] == "secret"
        return {"ok": True, "summary": "Connected to Confluence.", "details": "visible_spaces_in_sample=1."}

    monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "confluence", fake_test)

    resp = await client.post(
        "/admin/tools/configs/test",
        data={
            "tool_name": "confluence",
            "project_id": "",
            "description": "Confluence access",
            "config_json": '{"confluence_url": "https://wiki.example.com/wiki", "confluence_auth_mode": "basic", "confluence_username": "alice", "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": true}]}',
            "confluence_password": "secret",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200
    assert "Connected to Confluence." in resp.text
    assert "visible_spaces_in_sample=1." in resp.text
