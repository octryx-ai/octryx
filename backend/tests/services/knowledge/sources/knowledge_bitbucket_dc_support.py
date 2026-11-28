"""Bitbucket Data Center behind an OIDC client-credentials IdP, both fakes behind every pinned transport."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

import app.services.connector_auth.oidc_token_cache as oidc_tokens
import app.services.knowledge.sources.connection_repositories as listing_module

SECRET = "s3cr3t-client-value"


class FakeIdp:
    def __init__(self) -> None:
        self.issued = 0
        self.requests = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if (form.get("grant_type"), form.get("client_id"), form.get("client_secret")) != (
                "client_credentials", "octryx-client", SECRET):
            return httpx.Response(401, json={"error": "invalid_client"})
        self.issued += 1
        return httpx.Response(200, json={"access_token": f"tok-{self.issued}", "token_type": "Bearer",
                                         "expires_in": 300})


class FakeDataCenter:
    def __init__(self, idp: FakeIdp) -> None:
        self.idp = idp
        self.requests: list[httpx.Request] = []
        self.repos = [{"slug": f"svc-{index:02d}", "name": f"Service {index:02d}", "project": {"key": "SHOP"}}
                      for index in range(29)]
        self.repos.append({"slug": "aws-shop-deployment", "name": "aws-shop-deployment",
                           "project": {"key": "SHOP"}})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "idp.example.test":
            return self.idp.handle(request)
        self.requests.append(request)
        if request.headers.get("Authorization") != f"Bearer tok-{self.idp.issued}":
            return httpx.Response(401)
        path, params = request.url.path, request.url.params
        if path.endswith("/default-branch"):
            return httpx.Response(200, json={"id": "refs/heads/main", "displayId": "main"})
        if path == "/bitbucket/rest/api/1.0/repos" or path == "/bitbucket/rest/api/1.0/projects/SHOP/repos":
            found = [repo for repo in self.repos if params.get("name", "").lower() in repo["name"].lower()]
            start, limit = int(params.get("start", 0)), int(params.get("limit", 25))
            page = found[start:start + limit]
            last = start + limit >= len(found)
            body = {"values": page, "start": start, "limit": limit, "size": len(page), "isLastPage": last}
            if not last:
                body["nextPageStart"] = start + limit
            return httpx.Response(200, json=body)
        return httpx.Response(404)


@pytest.fixture
def world(monkeypatch):
    import ipaddress

    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("203.0.113.20")}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)
    oidc_tokens.clear_token_cache()
    fake = FakeDataCenter(FakeIdp())

    def transport(*_args, inner=None, **_kwargs):
        return inner or httpx.MockTransport(fake.handle)

    monkeypatch.setattr(listing_module, "egress_transport", transport)
    monkeypatch.setattr(oidc_tokens, "egress_transport", transport)
    yield fake
    oidc_tokens.clear_token_cache()
