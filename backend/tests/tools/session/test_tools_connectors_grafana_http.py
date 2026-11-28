"""Grafana render, snapshot and dashboard tools and the HTTP request tool with approval for mutating requests."""

import ipaddress
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    ChangePreview,
    Session,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_grafana_extended_tools_cover_render_snapshot_and_dashboard_json(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            request = httpx.Request("GET", url, params=params)
            if url.endswith("/render/d-solo/acme-orders-overview"):
                return httpx.Response(200, content=b"png-bytes", headers={"content-type": "image/png"}, request=request)
            if url.endswith("/api/dashboards/uid/acme-orders-overview"):
                return httpx.Response(
                    200,
                    json={
                        "dashboard": {"title": "Acme Orders Overview", "version": 7},
                        "meta": {"slug": "acme-orders-overview"},
                    },
                    request=request,
                )
            raise AssertionError(f"unexpected url {url}")

        async def post(self, url, headers=None, json=None):
            request = httpx.Request("POST", url)
            if url.endswith("/api/snapshots"):
                return httpx.Response(
                    200,
                    json={
                        "url": "https://grafana.example.com/dashboard/snapshot/abc",
                        "deleteUrl": "https://grafana.example.com/api/snapshots-delete/abc",
                        "key": "abc",
                    },
                    request=request,
                )
            raise AssertionError(f"unexpected url {url}")

    import httpx

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="grafana-extended",
        project_config={
            "grafana_url": "https://grafana.example.com",
            "grafana_token": "grafana-token",
            # Connector writes need an exact-name grant (connector_ownership.py).
            "tool_policy": {"high_risk_grants": ["create_snapshot"]},
        },
    )

    rendered = await execute_tool(
        "render_panel_as_image",
        {"dashboard_uid": "acme-orders-overview", "panel_id": 4},
        context,
    )
    assert rendered["content_type"] == "image/png"
    assert rendered["bytes"] == 9

    snapshot = await execute_tool("create_snapshot", {"dashboard_uid": "acme-orders-overview"}, context)
    assert snapshot["key"] == "abc"

    dashboard = await execute_tool("get_dashboard_json", {"dashboard_uid": "acme-orders-overview"}, context)
    assert dashboard["title"] == "Acme Orders Overview"
    assert dashboard["version"] == 7


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_http_request_tool(monkeypatch):
    class FakeResponse:
        async def request(self, method, url, headers=None, params=None, content=None, **kwargs):
            assert method == "GET"
            assert url == "https://example.com/health"
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                text='{"ok":true}',
                request=request,
            )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, headers=None, params=None, content=None, **kwargs):
            return await FakeResponse().request(method, url, headers=headers, params=params, content=content, **kwargs)

    async def _resolve_hostname_ips(hostname: str, port: int | None):
        assert hostname == "example.com"
        # A host that resolves to nothing is refused (fail closed), so resolve to a public address.
        return {ipaddress.ip_address("93.184.216.34")}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve_hostname_ips)
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *args, **kwargs: FakeClient(),
    )

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
    )
    result = await execute_tool("http_request", {"url": "https://example.com/health"}, context)
    assert result["status_code"] == 200
    assert result["body"] == '{"ok":true}'


@pytest.mark.asyncio
async def test_http_request_tool_requires_approval_for_mutating_requests(db, monkeypatch, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="change",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    class _UnexpectedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            raise AssertionError(f"unexpected outbound request: {method} {url}")

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *args, **kwargs: _UnexpectedClient(),
    )

    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["viewer"],
        session_id=session.id,
        project_config={},
        capability_type="change",
        agent_mode_key="change",
        db=db,
    )
    result = await execute_tool(
        "http_request",
        {"method": "POST", "url": "https://example.com/api/deploy", "body": {"force": True}},
        context,
    )

    assert result["approval_required"] is True
    assert result["tool_name"] == "http_request"
    assert result["change_preview"]["kind"] == "http_request"
    assert result["change_preview"]["method"] == "POST"
    assert result["change_preview"]["url"] == "https://example.com/api/deploy"
    preview = (
        await db.execute(select(ChangePreview).where(ChangePreview.approval_id == result["approval_id"]))
    ).scalar_one()
    assert preview.tool_name == "http_request"
