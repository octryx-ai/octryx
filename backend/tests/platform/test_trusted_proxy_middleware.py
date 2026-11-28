"""Trusted-proxy boundary: the ASGI middleware and the cookie policy behind it."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

import app.trusted_proxy_policy as boundary
from app.auth_cookie_policy import (
    INSECURE_REASON_LOCAL_DEBUG,
    SECURE_REASON_HTTPS,
    resolve_auth_cookie_policy,
)
from app.middleware.security.trusted_proxy import TrustedProxyBoundaryMiddleware
from app.services.auth.audit import client_ip_from_request
from app.trusted_proxy_policy import client_identity, rate_limit_client_key
from tests.support.trusted_proxy_test_utils import (
    PROXY_NETWORK,
    PROXY_PEER,
    REAL_CLIENT,
    REMOTE_PEER,
    boundary_get,
    request,
    settings,
)


@pytest.mark.asyncio
async def test_asgi_boundary_ignores_spoofed_headers_from_an_untrusted_peer():
    payload = await boundary_get(
        settings(trusted_proxy_ips=PROXY_NETWORK),
        peer=REMOTE_PEER,
        headers={"x-forwarded-for": "127.0.0.1", "x-forwarded-proto": "https"},
    )
    assert payload == {"client": REMOTE_PEER, "scheme": "http", "peer": REMOTE_PEER, "trusted": False}


@pytest.mark.asyncio
async def test_asgi_boundary_applies_a_trusted_proxy_claim_and_keeps_the_peer():
    payload = await boundary_get(
        settings(trusted_proxy_ips=PROXY_NETWORK),
        peer=PROXY_PEER,
        headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"},
    )
    assert payload == {"client": REAL_CLIENT, "scheme": "https", "peer": PROXY_PEER, "trusted": True}


@pytest.mark.asyncio
async def test_asgi_boundary_preserves_direct_local_debug_requests():
    payload = await boundary_get(settings(trusted_proxy_ips=""), peer="127.0.0.1", headers={})
    assert payload == {"client": "127.0.0.1", "scheme": "http", "peer": "127.0.0.1", "trusted": False}


@pytest.mark.asyncio
async def test_recorded_identity_is_used_by_the_shared_accessors():
    captured: dict[str, object] = {}

    async def capture(scope, receive, send):
        built = Request(scope, receive)
        captured["address"] = rate_limit_client_key(built)
        captured["audit"] = client_ip_from_request(built)
        captured["scheme"] = client_identity(built).scheme
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = TrustedProxyBoundaryMiddleware(capture, settings=settings(trusted_proxy_ips=PROXY_NETWORK))
    transport = ASGITransport(app=middleware, client=(PROXY_PEER, 44321))
    async with AsyncClient(transport=transport, base_url="http://octryx.example") as client:
        await client.get(
            "/api/v1/health",
            headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"},
        )

    assert captured == {"address": REAL_CLIENT, "audit": REAL_CLIENT, "scheme": "https"}


@pytest.mark.asyncio
async def test_asgi_boundary_upgrades_a_trusted_websocket_and_leaves_others_alone():
    captured: list[dict] = []

    async def echo(scope, receive, send):
        recorded = scope[boundary.SCOPE_STATE_KEY]
        captured.append({"client": scope["client"][0], "scheme": scope["scheme"], "peer": recorded.peer_address})

    middleware = TrustedProxyBoundaryMiddleware(echo, settings=settings(trusted_proxy_ips=PROXY_NETWORK))
    for peer in (PROXY_PEER, REMOTE_PEER):
        await middleware(
            {
                "type": "websocket",
                "scheme": "ws",
                "path": "/api/v1/sessions/stream",
                "headers": [(b"x-forwarded-for", REAL_CLIENT.encode()), (b"x-forwarded-proto", b"https")],
                "client": (peer, 44321),
            },
            None,
            None,
        )

    assert captured == [
        {"client": REAL_CLIENT, "scheme": "wss", "peer": PROXY_PEER},
        {"client": REMOTE_PEER, "scheme": "ws", "peer": REMOTE_PEER},
    ]


@pytest.mark.asyncio
async def test_asgi_boundary_passes_non_request_scopes_through_untouched():
    seen: list[dict] = []

    async def echo(scope, receive, send):
        seen.append(scope)

    middleware = TrustedProxyBoundaryMiddleware(echo, settings=settings(trusted_proxy_ips=PROXY_NETWORK))
    lifespan_scope = {"type": "lifespan"}
    await middleware(lifespan_scope, None, None)
    assert seen == [lifespan_scope]
    assert boundary.SCOPE_STATE_KEY not in lifespan_scope


@pytest.mark.asyncio
async def test_asgi_boundary_handles_a_request_without_a_peer():
    captured: dict = {}

    async def echo(scope, receive, send):
        captured["client"] = scope["client"]
        captured["key"] = rate_limit_client_key(Request(scope))

    middleware = TrustedProxyBoundaryMiddleware(echo, settings=settings(trusted_proxy_ips=PROXY_NETWORK))
    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/health",
            "scheme": "http",
            "headers": [(b"x-forwarded-for", REAL_CLIENT.encode())],
            "client": None,
        },
        None,
        None,
    )
    assert captured == {"client": None, "key": boundary.UNKNOWN_CLIENT_ADDRESS}


@pytest.mark.asyncio
async def test_asgi_boundary_trusts_an_ipv6_proxy_peer():
    payload = await boundary_get(
        settings(trusted_proxy_ips="2001:db8::/32"),
        peer="2001:db8::5",
        headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"},
    )
    assert payload == {"client": REAL_CLIENT, "scheme": "https", "peer": "2001:db8::5", "trusted": True}


@pytest.mark.asyncio
async def test_asgi_boundary_combines_repeated_headers_across_field_lines():
    payload = await boundary_get(
        settings(trusted_proxy_ips=PROXY_NETWORK),
        peer=PROXY_PEER,
        headers=[
            ("x-forwarded-for", "192.0.2.66"),
            ("x-forwarded-proto", "http"),
            ("x-forwarded-for", REAL_CLIENT),
            ("x-forwarded-proto", "https"),
        ],
    )
    assert payload == {"client": REAL_CLIENT, "scheme": "https", "peer": PROXY_PEER, "trusted": True}


def test_app_installs_the_boundary_as_the_outermost_middleware():
    from app.main import app

    assert app.user_middleware[0].cls is TrustedProxyBoundaryMiddleware


def test_cookie_policy_reports_direct_https_separately():
    decision = resolve_auth_cookie_policy(
        request(peer=PROXY_PEER, scheme="https"),
        settings(debug=True, force_secure_auth_cookies=False, trusted_proxy_ips=PROXY_NETWORK),
    )
    assert decision.secure_reason == SECURE_REASON_HTTPS


@pytest.mark.asyncio
async def test_local_debug_exemption_survives_the_boundary_for_a_direct_loopback_peer():
    local_debug = settings(debug=True, force_secure_auth_cookies=False)
    captured: dict = {}

    async def resolve(scope, receive, send):
        captured["decision"] = resolve_auth_cookie_policy(Request(scope, receive), local_debug)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    transport = ASGITransport(app=TrustedProxyBoundaryMiddleware(resolve, settings=local_debug), client=("127.0.0.1", 1))
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        await client.get("/api/v1/health")

    assert captured["decision"].secure is False
    assert captured["decision"].secure_reason == INSECURE_REASON_LOCAL_DEBUG


@pytest.mark.asyncio
async def test_trusted_proxy_rewrite_does_not_buy_the_local_debug_exemption():
    local_debug = settings(debug=True, force_secure_auth_cookies=False, trusted_proxy_ips=PROXY_NETWORK)
    captured: dict = {}

    async def resolve(scope, receive, send):
        captured["decision"] = resolve_auth_cookie_policy(Request(scope, receive), local_debug)
        captured["client"] = scope["client"][0]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    transport = ASGITransport(
        app=TrustedProxyBoundaryMiddleware(resolve, settings=local_debug), client=(PROXY_PEER, 1)
    )
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        await client.get("/api/v1/health", headers={"x-forwarded-for": "127.0.0.1"})

    assert captured["client"] == "127.0.0.1"
    assert captured["decision"].secure is True
    assert captured["decision"].local_debug_exemption is False
