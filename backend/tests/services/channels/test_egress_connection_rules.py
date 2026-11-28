"""Contract (#S8): one egress rule per connection, whichever path sends the credential."""

from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import httpcore
import httpx
import pytest

from app.services.outbound_egress import (
    CONNECTION_GITHUB,
    CONNECTION_GITLAB,
    CONNECTION_VAULT,
    EgressRefusedError,
    UnknownEgressConnectionError,
    connection_rule,
    egress_transport,
)
from app.services.outbound_url_policy import EGRESS_SCOPE_NO_POD_LOCAL, EGRESS_SCOPE_PUBLIC_ONLY, OutboundURLPolicyError

GITHUB = "https://github.corp.example/api/v3"
GITLAB = "https://gitlab.corp.example/api/v4"
PRIVATE = "10.20.0.5"


@pytest.fixture
def network(monkeypatch):
    state = {"allowlist": {}, "connects": []}

    async def _resolve(hostname: str, port: int | None):
        if hostname == "pod.corp.example":
            return {ipaddress.ip_address("127.0.0.1")}
        return {ipaddress.ip_address(PRIVATE if hostname.endswith(".corp.example") else "203.0.113.10")}

    async def _allowlist(connection: str) -> frozenset[str]:
        return state["allowlist"].get(connection, frozenset())

    async def _connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        state["connects"].append((host, port))
        raise httpcore.ConnectError("recorded")

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _allowlist)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", _connect)
    return state


def _github_config():
    return {"github_url": GITHUB, "github_token": "token", "github_owner": "acme"}


async def _github_tool():
    from app.tools.connectors import github

    await github._http_json("GET", f"{GITHUB}/user", headers={"Authorization": "Bearer token"})


async def _github_design_delivery(monkeypatch):
    from app.services.design_delivery_sync import github_fetch

    async def _config(_db):
        return _github_config()

    monkeypatch.setattr(github_fetch, "_resolved_github_config", _config)
    await github_fetch.fetch_github_releases(SimpleNamespace(), owner="acme", repo="platform", limit=5)


async def _github_connector_service(monkeypatch):
    from app.services.github_connector import service

    async def _config(_db):
        return _github_config()

    monkeypatch.setattr(service, "_resolved_github_config", _config)
    await service.list_github_connector_repositories(SimpleNamespace(), limit=5)


async def _github_connection_test(monkeypatch):
    from app.services.connector_test.collab import test_github_connection

    await test_github_connection(_github_config(), httpx_module=httpx)


async def _gitlab_tool():
    from app.tools.connectors import gitlab

    await gitlab._http_json("GET", f"{GITLAB}/projects", headers={"PRIVATE-TOKEN": "token"})


async def _gitlab_design_delivery(monkeypatch):
    from app.services.design_delivery_sync import gitlab_fetch

    async def _config(_db):
        return {"gitlab_url": GITLAB, "gitlab_token": "token"}

    monkeypatch.setattr(gitlab_fetch, "resolved_gitlab_config", _config)
    await gitlab_fetch.fetch_gitlab_releases(SimpleNamespace(), project_path="acme%2Fplatform", limit=5)


PATHS = {
    "github_tool": (CONNECTION_GITHUB, lambda mp: _github_tool()),
    "github_design_delivery": (CONNECTION_GITHUB, _github_design_delivery),
    "github_connector_service": (CONNECTION_GITHUB, _github_connector_service),
    "github_connection_test": (CONNECTION_GITHUB, _github_connection_test),
    "gitlab_tool": (CONNECTION_GITLAB, lambda mp: _gitlab_tool()),
    "gitlab_design_delivery": (CONNECTION_GITLAB, _gitlab_design_delivery),
}


def _reason(error: BaseException | None) -> str | None:
    while error is not None:
        if isinstance(error, OutboundURLPolicyError):
            return error.reason
        error = error.__cause__ or error.__context__
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(PATHS))
async def test_every_path_applies_the_connection_rule_and_its_allowlist(network, monkeypatch, path):
    connection, call = PATHS[path]
    host = "github.corp.example" if connection == CONNECTION_GITHUB else "gitlab.corp.example"

    try:
        await call(monkeypatch)
    except Exception as refused:  # noqa: BLE001 - each path reports the refusal its own way
        error = refused
    else:
        error = None
    if path == "github_connection_test":
        # The connection test reports failures as a result; the refusal is proven by the connects.
        assert network["connects"] == []
    else:
        assert _reason(error) == "private_address_not_allowlisted"
    assert network["connects"] == []

    network["allowlist"] = {connection: frozenset({f"{host}:443"})}
    with pytest.raises(Exception):  # noqa: B017 - the recorded socket refuses after the connect
        await call(monkeypatch)
        if path == "github_connection_test":
            raise RuntimeError("connection test reported")
    assert network["connects"] == [(PRIVATE, 443)]


def test_the_rules_are_the_connection_types_not_the_call_sites():
    for connection in ("jira", "confluence", "bitbucket", "github", "gitlab", "servicenow"):
        rule = connection_rule(connection)
        assert rule.scope == EGRESS_SCOPE_PUBLIC_ONLY and rule.private_allowlist
    private_network = connection_rule(CONNECTION_VAULT)
    assert private_network.scope == EGRESS_SCOPE_NO_POD_LOCAL and not private_network.private_allowlist
    with pytest.raises(UnknownEgressConnectionError):
        egress_transport("vault-without-a-rule")


@pytest.mark.asyncio
async def test_private_network_integrations_reach_the_private_network_but_never_the_pod(network):
    from app.tools.connectors.vault import _http_json

    with pytest.raises(httpx.ConnectError):
        await _http_json("GET", "https://vault.corp.example/v1/sys/health")
    assert network["connects"] == [(PRIVATE, 443)]
    with pytest.raises(EgressRefusedError) as refused:
        await _http_json("GET", "https://pod.corp.example/v1/sys/health")
    assert refused.value.reason == "blocked_address"
    assert network["connects"] == [(PRIVATE, 443)]
