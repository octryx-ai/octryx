"""Contract: no credentialed call reaches the pod, the private network or cloud metadata.

- the outbound URL policy refuses loopback, link-local/metadata, private and IPv4-in-IPv6 targets
  after DNS resolution (``public_only``), admits a public host, and in ``no_pod_local`` admits the
  private network but never the pod or metadata;
- Source Sync refuses such a connection with ``egress_refused`` before anything is sent (reads and
  the ServiceNow token grant) and never follows a redirect;
- a credentialed connector client refuses a redirect to a private address before the hop is sent;
- the loopback exemption for local stubs is honoured only for its listed hosts on a development
  profile with loopback origins, and startup refuses it anywhere else;
- the exemption is never set in Helm.
"""

from __future__ import annotations

import ipaddress
import pathlib

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.contract import REASON_EGRESS_REFUSED, ConnectorError
from app.services.knowledge.sources.sync.http import SourceReader
from app.services.knowledge.sources.sync.servicenow_connection import servicenow_connection
from app.services.outbound_egress import (
    CONNECTION_JIRA,
    CONNECTION_VAULT,
    EgressRefusedError,
    egress_transport,
)
from app.services.outbound_url_policy import (
    EGRESS_SCOPE_NO_POD_LOCAL,
    OutboundURLPolicyError,
    validate_outbound_url,
)
from tests.egress_support import stub_settings, use_stub_settings

REPO = pathlib.Path(__file__).resolve().parents[2]
PUBLIC = ipaddress.ip_address("203.0.113.10")


@pytest.fixture
def dns(monkeypatch):
    """Resolve ``*.private.test`` to a private address and everything else to a public one."""

    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("10.0.0.5")} if hostname.endswith(".private.test") else {PUBLIC}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)


@pytest.fixture(autouse=True)
def no_private_host_allowlist(monkeypatch):
    """No connection type has an on-prem allowlist entry here (``test_egress_private_hosts.py`` covers it)."""

    async def _none(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _none)


def _recording_transport(sent: list[str], *, status: int = 200, location: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        headers = {"location": location} if location else {}
        return httpx.Response(status, json={"ok": True}, headers=headers)

    return httpx.MockTransport(handler)


def _connection(base_url: str) -> SourceConnection:
    return SourceConnection(kind="confluence", base_url=base_url, principal="sync-bot", secret="pw")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:2480/api",  # a service on the pod loopback
        "http://127.0.0.1:9911/credentials",  # the AWS credentials sidecar
        "http://localhost:4000",  # LiteLLM
        "http://[::1]:2480",
        "http://[::ffff:127.0.0.1]:2480",  # IPv4-mapped loopback
        "http://169.254.169.254/latest/meta-data",  # instance metadata
        "http://169.254.170.2/v2/credentials",  # container credentials
        "http://[fd00:ec2::254]/latest",  # AWS IPv6 metadata
        "http://metadata.google.internal/computeMetadata",
        "http://10.1.2.3",
        "http://172.16.0.9",
        "http://192.168.1.1",
        "http://100.64.0.1",
        "http://wiki.private.test/wiki",  # a hostname that resolves to a private address
        "file:///etc/passwd",
    ],
)
async def test_the_policy_refuses_pod_metadata_and_private_targets(dns, url):
    with pytest.raises(OutboundURLPolicyError):
        await validate_outbound_url(url)


@pytest.mark.asyncio
async def test_the_policy_admits_a_public_host_and_refuses_an_unresolvable_one(dns, monkeypatch):
    assert await validate_outbound_url("https://wiki.example.test/wiki") == "https://wiki.example.test/wiki"

    async def _nothing(hostname: str, port: int | None):
        return set()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _nothing)
    with pytest.raises(OutboundURLPolicyError) as refused:
        await validate_outbound_url("https://gone.example.test")
    assert refused.value.reason == "unresolvable_host"


@pytest.mark.asyncio
async def test_no_pod_local_admits_the_private_network_but_never_the_pod_or_metadata(dns):
    assert await validate_outbound_url("https://vault.private.test", scope=EGRESS_SCOPE_NO_POD_LOCAL)
    for url in ("http://127.0.0.1:2480", "http://169.254.169.254", "http://[::ffff:127.0.0.1]"):
        with pytest.raises(OutboundURLPolicyError):
            await validate_outbound_url(url, scope=EGRESS_SCOPE_NO_POD_LOCAL)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url", ["http://127.0.0.1:2480", "http://169.254.169.254", "https://wiki.private.test/wiki"]
)
async def test_source_sync_refuses_a_pod_metadata_or_private_connection_before_sending(dns, base_url):
    sent: list[str] = []
    reader = SourceReader(_connection(base_url), transport=_recording_transport(sent))

    with pytest.raises(ConnectorError) as refused:
        await reader.get_json("/rest/api/content")
    assert refused.value.reason == REASON_EGRESS_REFUSED
    assert sent == []


@pytest.mark.asyncio
async def test_source_sync_reads_a_public_host_and_never_follows_a_redirect(dns):
    sent: list[str] = []
    reader = SourceReader(_connection("https://wiki.example.test/wiki"), transport=_recording_transport(sent))
    assert await reader.get_json("/rest/api/content") == {"ok": True}

    redirected: list[str] = []
    reader = SourceReader(
        _connection("https://wiki.example.test/wiki"),
        transport=_recording_transport(redirected, status=302, location="http://127.0.0.1:9911/credentials"),
    )
    with pytest.raises(ConnectorError):
        await reader.get_json("/rest/api/content")
    assert redirected == ["https://wiki.example.test/wiki/rest/api/content"]


@pytest.mark.asyncio
async def test_the_servicenow_token_grant_passes_the_same_check(dns):
    connection = servicenow_connection(
        {
            "servicenow_url": "https://sn.private.test",
            "servicenow_auth_mode": "oidc_client_credentials",
            "servicenow_token_url": "https://sn.private.test/oauth_token.do",
            "servicenow_client_id": "client",
            "servicenow_client_secret": "client-secret",
        }
    )
    sent: list[str] = []
    with pytest.raises(ConnectorError) as refused:
        await connection.request_auth(transport=_recording_transport(sent))
    assert refused.value.reason == REASON_EGRESS_REFUSED
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connection", "target"),
    [(CONNECTION_JIRA, "http://10.0.0.5/steal"), (CONNECTION_VAULT, "http://127.0.0.1:9911/")],
)
async def test_a_credentialed_connector_client_refuses_a_redirect_to_a_refused_address(dns, connection, target):
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    transport = egress_transport(connection, inner=httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(EgressRefusedError) as refused:
            await client.get("https://jira.example.test/rest/api/2/myself", auth=("bot", "token"))
    # An httpx.HTTPError, so the connectors' existing error handling reports a failed call.
    assert isinstance(refused.value, httpx.HTTPError)
    assert "10.0.0.5" not in str(refused.value) and "127.0.0.1" not in str(refused.value)
    assert sent == ["https://jira.example.test/rest/api/2/myself"]


@pytest.mark.asyncio
async def test_the_loopback_exemption_admits_only_its_stubs_and_only_in_local_acceptance(monkeypatch):
    stub = _connection("http://127.0.0.1:8095")
    sent: list[str] = []

    use_stub_settings(monkeypatch, stub_settings())
    assert await SourceReader(stub, transport=_recording_transport(sent)).get_json("/rest/api/content")
    assert sent == ["http://127.0.0.1:8095/rest/api/content"]
    with pytest.raises(ConnectorError):  # a loopback port that is not listed stays refused
        await SourceReader(_connection("http://127.0.0.1:2480"), transport=_recording_transport(sent)).get_json("/x")

    for settings in (
        stub_settings(profile="production"),
        stub_settings(origins="https://octryx.example.com"),
        stub_settings(hosts=""),
    ):
        use_stub_settings(monkeypatch, settings)
        with pytest.raises(ConnectorError) as refused:
            await SourceReader(stub, transport=_recording_transport(sent)).get_json("/rest/api/content")
        assert refused.value.reason == REASON_EGRESS_REFUSED
    assert len(sent) == 1


_SECURE = {
    "jwt_secret": ("egress-t" + "est-jwt-secret-0123456789abcd"),
    "encryption_key": ("egress-t" + "est-encryption-key-012345"),
    "admin_default_password": ("egress-T" + "est-Pw-12345"),
    "admin_email": "admin@egress.test",
    "database_url": "postgresql+asyncpg://octryx:unused@postgres:5432/octryx",
    "force_secure_auth_cookies": True,
    "debug": False,
}


def test_startup_refuses_the_exemption_outside_local_acceptance_and_accepts_the_ranger_shape():
    hosts = "127.0.0.1:8095,127.0.0.1:8096"
    loopback = "http://localhost:8090,http://127.0.0.1:8090"
    for profile, origins in (("production", loopback), ("local", "https://octryx.example.com")):
        with pytest.raises(ValidationError) as refused:
            Settings(
                **_SECURE, runtime_profile=profile, cors_allowed_origins=origins, source_sync_allow_loopback_hosts=hosts
            )
        assert "loopback stub exemption is development-only" in str(refused.value)
    for entry in ("10.0.0.5:80", "localhost:8095", "127.0.0.1"):
        with pytest.raises(ValidationError):
            Settings(
                **_SECURE,
                runtime_profile="staging",
                cors_allowed_origins=loopback,
                source_sync_allow_loopback_hosts=entry,
            )

    local_staging = Settings(
        **_SECURE, runtime_profile="staging", cors_allowed_origins=loopback, source_sync_allow_loopback_hosts=hosts
    )
    assert local_staging.source_sync_allow_loopback_hosts == hosts


def test_the_exemption_is_never_set_in_helm():
    for path in (REPO / "deployment/helm").rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".yml", ".tpl", ".txt", ".json"}:
            text = path.read_text(errors="ignore")
            assert "SOURCE_SYNC_ALLOW_LOOPBACK" not in text and "source_sync_allow_loopback" not in text, path
