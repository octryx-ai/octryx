"""Contract: the chat connector tools reach local loopback stubs exactly as Source Sync does.

``app/loopback_stub_policy.py`` is the one owner of the loopback stub
exemption, and the pinned egress transport asks it on every request:

- a Jira tool request to a listed loopback pair connects to that pair only while the policy is
  active (listed, development profile, loopback origins), and is ``blocked_address`` otherwise;
- an unlisted loopback port, another loopback address, ``localhost``, the credentials sidecar and
  instance metadata stay refused while it is active;
- connection types without a local stub never get the exemption;
- a non-development profile refuses the exemption at startup.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.loopback_stub_policy import LOOPBACK_STUB_CONNECTIONS
from app.services.outbound_egress import (
    CONNECTION_BITBUCKET,
    CONNECTION_CONFLUENCE,
    CONNECTION_CUSTOM_REST,
    CONNECTION_GITHUB,
    CONNECTION_GRAFANA,
    CONNECTION_JIRA,
    CONNECTION_PUBLIC_WEB,
    CONNECTION_SERVICENOW,
    EgressRefusedError,
    egress_transport,
)
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_query_metadata import ListJiraIssueTypes
from tests.egress_support import LOOPBACK_ORIGINS, STUB_LOOPBACK_HOSTS, stub_settings, use_stub_settings


def _jira_context(jira_url: str) -> ToolContext:
    return ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={"jira_url": jira_url, "jira_email": "bot@stub.test", "jira_token": "not-a-real-token"},
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root="/tmp",
    )


async def _jira_stub(seen: list[bytes]) -> asyncio.base_events.Server:
    body = json.dumps({"issueTypes": [{"id": "1", "name": "Task", "subtask": False}]}).encode()

    async def _answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    return await asyncio.start_server(_answer, "127.0.0.1", 0)


@pytest.mark.asyncio
async def test_a_jira_tool_reaches_a_listed_stub_only_while_the_policy_is_active(monkeypatch):
    seen: list[bytes] = []
    server = await _jira_stub(seen)
    port = server.sockets[0].getsockname()[1]
    context = _jira_context(f"http://127.0.0.1:{port}")
    try:
        use_stub_settings(monkeypatch, stub_settings(hosts=f"127.0.0.1:{port}"))
        result = await ListJiraIssueTypes().execute({"project_key": "OPS"}, context)
        assert result["issue_types"] == [{"id": "1", "name": "Task", "description": None, "subtask": False}]
        assert len(seen) == 1 and seen[0].startswith(b"GET /rest/api/3/project/OPS ")
        assert f"Host: 127.0.0.1:{port}\r\n".encode() in seen[0]

        for inactive in (
            stub_settings(hosts=""),
            stub_settings(hosts=f"127.0.0.1:{port}", profile="production"),
            stub_settings(hosts=f"127.0.0.1:{port}", origins="https://octryx.example.com"),
        ):
            use_stub_settings(monkeypatch, inactive)
            with pytest.raises(EgressRefusedError) as refused:
                await ListJiraIssueTypes().execute({"project_key": "OPS"}, context)
            assert refused.value.reason == "blocked_address"
            assert "127.0.0.1" not in str(refused.value)
    finally:
        server.close()
        await server.wait_closed()
    assert len(seen) == 1  # nothing reached the stub while the policy was inactive


def _refusing_handler(sent: list[str]):
    def _handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={})

    return _handler


async def _reason(connection: str, url: str, sent: list[str]) -> str | None:
    transport = egress_transport(connection, inner=httpx.MockTransport(_refusing_handler(sent)))
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            await client.get(url, auth=("bot", "token"))
        except EgressRefusedError as refused:
            return refused.reason
    return None


@pytest.mark.asyncio
async def test_only_the_listed_pairs_are_exempt_while_the_policy_is_active(monkeypatch):
    use_stub_settings(monkeypatch, stub_settings(hosts=STUB_LOOPBACK_HOSTS))
    sent: list[str] = []

    assert await _reason(CONNECTION_JIRA, "http://127.0.0.1:8096/rest/api/2/myself", sent) is None
    assert await _reason(CONNECTION_CONFLUENCE, "http://127.0.0.1:8095/rest/api/content", sent) is None
    for url, reason in (
        ("http://127.0.0.1:8097/rest/api/2/myself", "blocked_address"),  # unlisted port
        ("http://127.0.0.2:8096/rest/api/2/myself", "blocked_address"),  # another loopback address
        ("http://[::1]:8096/rest/api/2/myself", "blocked_address"),
        ("http://localhost:8096/rest/api/2/myself", "blocked_host"),  # names are never listed
        ("http://127.0.0.1:2480/api/v1/server", "blocked_address"),  # a service on the pod loopback
        ("http://127.0.0.1:9911/credentials", "blocked_address"),  # AWS credentials sidecar
        ("http://169.254.169.254/latest/meta-data/", "blocked_address"),  # instance metadata
    ):
        assert await _reason(CONNECTION_JIRA, url, sent) == reason, url
    for connection in (CONNECTION_GRAFANA, CONNECTION_SERVICENOW, CONNECTION_PUBLIC_WEB):
        assert await _reason(connection, "http://127.0.0.1:8096/api", sent) == "blocked_address", connection
    assert sent == ["http://127.0.0.1:8096/rest/api/2/myself", "http://127.0.0.1:8095/rest/api/content"]


@pytest.mark.asyncio
async def test_with_no_exemption_set_every_loopback_target_is_refused_as_before():
    # The real settings of the test run: the variable is unset, so the policy reads it as empty.
    sent: list[str] = []
    for connection, url in (
        (CONNECTION_JIRA, "http://127.0.0.1:8096/rest/api/2/myself"),
        (CONNECTION_CONFLUENCE, "http://127.0.0.1:8095/rest/api/content"),
    ):
        assert await _reason(connection, url, sent) == "blocked_address"
    assert sent == []


def test_a_non_development_profile_refuses_the_exemption_at_startup():
    secure = {
        "jwt_secret": ("stub-te" + "st-jwt-secret-0123456789abcdef"),
        "encryption_key": ("stub-te" + "st-encryption-key-0123456"),
        "admin_default_password": ("stub-Te" + "st-Pw-12345"),
        "admin_email": "admin@stub.test",
        "database_url": "postgresql+asyncpg://octryx:unused@postgres:5432/octryx",
        "force_secure_auth_cookies": True,
        "debug": False,
    }
    with pytest.raises(ValidationError) as refused:
        Settings(
            **secure,
            runtime_profile="production",
            cors_allowed_origins=LOOPBACK_ORIGINS,
            source_sync_allow_loopback_hosts=STUB_LOOPBACK_HOSTS,
        )
    assert "loopback stub exemption is development-only" in str(refused.value)


def test_the_stubbed_connection_types_are_exactly_confluence_jira_github_bitbucket_and_custom_rest():
    assert LOOPBACK_STUB_CONNECTIONS == {
        CONNECTION_BITBUCKET, CONNECTION_CONFLUENCE, CONNECTION_CUSTOM_REST, CONNECTION_GITHUB, CONNECTION_JIRA}


@pytest.mark.asyncio
async def test_a_local_rest_api_is_reachable_for_custom_rest_only_with_the_dev_switch(monkeypatch):
    """A REST API on the Mac's loopback is a Custom REST target only while the local switch is set; with a
    production profile, or without the listed host:port, loopback stays refused (SSRF protection)."""
    sent: list[str] = []
    use_stub_settings(monkeypatch, stub_settings(hosts="127.0.0.1:8601"))
    assert await _reason(CONNECTION_CUSTOM_REST, "http://127.0.0.1:8601/api/items", sent) is None
    assert await _reason(CONNECTION_CUSTOM_REST, "http://127.0.0.1:8602/api/items", sent) == "blocked_address"
    assert await _reason(CONNECTION_CUSTOM_REST, "http://169.254.169.254/latest/meta-data", sent) == "blocked_address"

    use_stub_settings(monkeypatch, stub_settings(hosts="127.0.0.1:8601", profile="production"))
    assert await _reason(CONNECTION_CUSTOM_REST, "http://127.0.0.1:8601/api/items", sent) == "blocked_address"
    assert sent == ["http://127.0.0.1:8601/api/items"]


@pytest.mark.asyncio
async def test_a_local_fake_github_is_reachable_only_while_the_policy_is_active(monkeypatch):
    """Local dev loop: a run's branch and pull request calls reach the fake GitHub on loopback."""
    sent: list[str] = []
    use_stub_settings(monkeypatch, stub_settings(hosts="127.0.0.1:8434"))
    assert await _reason(CONNECTION_GITHUB, "http://127.0.0.1:8434/api/v3/repos/octryx/mini", sent) is None
    assert await _reason(CONNECTION_GITHUB, "http://127.0.0.1:8435/api/v3/repos/octryx/mini", sent) == "blocked_address"

    use_stub_settings(monkeypatch, stub_settings(hosts="127.0.0.1:8434", profile="production"))
    assert await _reason(CONNECTION_GITHUB, "http://127.0.0.1:8434/api/v3/repos/octryx/mini", sent) == "blocked_address"
    assert sent == ["http://127.0.0.1:8434/api/v3/repos/octryx/mini"]
