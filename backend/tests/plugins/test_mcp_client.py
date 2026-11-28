"""MCP server registry and connections: public dicts redact secrets, unregistering cleans up live resources, tokens refresh, HTTP and CLI sessions connect, and the auth status reports registration and expiry."""

import asyncio
import contextlib
import sys
import types

import pytest

from app.plugins.mcp.client import MCPClientManager
from app.plugins.mcp.models import MCPServerConfig, OAuthConfig, TransportType


class _CloseableSession:
    def __init__(self):
        self.closed = asyncio.Event()

    async def close(self):
        self.closed.set()


class _FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


class _MissingProcess:
    def terminate(self):
        raise ProcessLookupError("process already exited")


class _FakeMcpClientSession:
    def __init__(self, read, write):
        self.read = read
        self.write = write
        self.closed = asyncio.Event()
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.closed.set()
        return False

    async def initialize(self):
        assert self.entered, "initialize() on a session that was never entered never gets an answer"
        return None

    async def list_tools(self):
        return types.SimpleNamespace(tools=[])


def test_mcp_server_public_dict_redacts_env_headers_and_oauth_secrets():
    config = MCPServerConfig(
        name="context7",
        command="npx",
        args=["-y", "ctx7"],
        env={"CONTEXT7_API_KEY": "ctx7-secret-value", "AWS_REGION": "eu-central-1"},
        headers={"Authorization": ("Bearer abc1" + "23456789"), "X-Trace": "trace-1"},
        oauth=OAuthConfig(
            client_id="client-1",
            client_secret="oauth-secret",
            token_url="https://example.test/token",
            access_token="access-token-value",
            refresh_token="refresh-token-value",
            token_expires_at=123.0,
        ),
        metadata={"catalog_slug": "context7", "secret_ref": "vault://secret"},
    )

    storage_payload = config.to_dict()
    public_payload = config.to_public_dict()

    assert storage_payload["env"]["CONTEXT7_API_KEY"] == "ctx7-secret-value"
    assert storage_payload["headers"]["Authorization"] == ("Bearer abc1" + "23456789")
    assert storage_payload["oauth"]["client_secret"] == "oauth-secret"
    assert public_payload["env"]["CONTEXT7_API_KEY"] == "[redacted]"
    assert public_payload["env"]["AWS_REGION"] == "eu-central-1"
    assert public_payload["headers"]["Authorization"] == "[redacted]"
    assert public_payload["headers"]["X-Trace"] == "trace-1"
    assert public_payload["oauth"]["client_secret"] == "[redacted]"
    assert public_payload["oauth"]["has_access_token"] is True
    assert public_payload["oauth"]["has_refresh_token"] is True
    assert public_payload["metadata"]["secret_ref"] == "[redacted]"


@pytest.mark.asyncio
async def test_unregister_server_cleans_up_live_resources():
    manager = MCPClientManager()
    fake_session = _CloseableSession()
    fake_process = _FakeProcess()

    manager._servers["demo"] = object()
    manager._locks["demo"] = asyncio.Lock()
    manager._sessions["demo"] = fake_session
    manager._tools["demo"] = [object()]
    manager._processes["demo"] = fake_process
    manager._oauth_configs["demo"] = object()

    manager.unregister_server("demo")

    await asyncio.wait_for(fake_session.closed.wait(), timeout=1)

    assert "demo" not in manager._servers
    assert "demo" not in manager._locks
    assert "demo" not in manager._sessions
    assert "demo" not in manager._tools
    assert "demo" not in manager._processes
    assert "demo" not in manager._oauth_configs
    assert fake_process.terminated is True


@pytest.mark.asyncio
async def test_unregister_server_ignores_missing_process():
    manager = MCPClientManager()
    manager._servers["demo"] = object()
    manager._locks["demo"] = asyncio.Lock()
    manager._processes["demo"] = _MissingProcess()

    manager.unregister_server("demo")

    assert "demo" not in manager._servers
    assert "demo" not in manager._locks
    assert "demo" not in manager._processes


@pytest.mark.asyncio
async def test_refresh_token_uses_oauth_helper(monkeypatch: pytest.MonkeyPatch):
    manager = MCPClientManager()
    oauth = OAuthConfig(token_url="https://example.test/token")
    manager._oauth_configs["demo"] = oauth
    seen: list[OAuthConfig] = []

    async def fake_fetch_token(config: OAuthConfig) -> bool:
        seen.append(config)
        return True

    monkeypatch.setattr("app.plugins.mcp.client._oauth_fetch_token", fake_fetch_token)

    assert await manager.refresh_token("demo") is True
    assert seen == [oauth]


@pytest.mark.asyncio
async def test_streamable_http_connection_passes_static_headers(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    @contextlib.asynccontextmanager
    async def fake_streamable_http_client(url, **kwargs):
        seen["url"] = url
        http_client = kwargs.get("http_client")
        seen["headers"] = dict(http_client.headers) if http_client is not None else {}
        yield object(), object(), None
        seen["transport_closed"] = True

    fake_module = types.SimpleNamespace(streamable_http_client=fake_streamable_http_client)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", fake_module)
    monkeypatch.setattr("app.plugins.mcp.client.ClientSession", _FakeMcpClientSession)

    manager = MCPClientManager()
    config = MCPServerConfig(
        name="context7",
        command="",
        transport=TransportType.STREAMABLE_HTTP,
        url="https://mcp.context7.com/mcp",
        headers={"CONTEXT7_API_KEY": "ctx7-test-key"},
    )

    assert await manager._connect_http("context7", config) is True
    assert seen["url"] == "https://mcp.context7.com/mcp"
    assert seen["headers"]["context7_api_key"] == "ctx7-test-key"
    session = manager.get_session("context7")
    assert await manager.disconnect("context7") is True
    assert session.closed.is_set() and seen["transport_closed"] is True


def test_get_auth_status_reports_registration_and_expiry(monkeypatch: pytest.MonkeyPatch):
    manager = MCPClientManager()
    manager._oauth_configs["demo"] = OAuthConfig(
        registration_url="https://example.test/register",
        token_expires_at=150.0,
    )
    monkeypatch.setattr("app.plugins.mcp.client.time.time", lambda: 200.0)

    assert manager.get_auth_status("demo") == {
        "needs_registration": True,
        "needs_auth": True,
        "has_token": False,
        "expires_at": 150.0,
    }
