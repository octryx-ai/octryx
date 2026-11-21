"""The ASGI CSRF boundary under the trusted-proxy boundary refuses foreign mutations before the app and trusts forwarded claims only from trusted peers."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.middleware.security.panel_csrf import (
    PanelCsrfBoundaryMiddleware,
    rejection_body,
    request_id_for_scope,
)
from app.middleware.security.trusted_proxy import TrustedProxyBoundaryMiddleware
from app.panel_csrf_policy import CSRF_REJECTION_DETAIL
from tests.panel_cookie_mutation_support import (
    ALLOWLIST_ORIGIN,
    APP_HOST,
    APP_ORIGIN,
    FOREIGN_ORIGIN,
    PANEL_PATH,
    POLICY_SETTINGS,
)
from tests.trusted_proxy_test_utils import PROXY_NETWORK, PROXY_PEER, REMOTE_PEER, header_pairs, settings

# --- the ASGI boundary under the real trusted-proxy boundary -----------------


def boundary_app(resolved_settings):
    """Trusted-proxy boundary over the panel boundary over an echoing app."""
    reached: list[str] = []

    async def echo(scope, receive, send):
        reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"reached"})

    stack = TrustedProxyBoundaryMiddleware(
        PanelCsrfBoundaryMiddleware(echo, settings=resolved_settings),
        settings=resolved_settings,
    )
    return stack, reached


async def boundary_post(resolved_settings, *, peer: str, headers) -> tuple[int, str, list[str]]:
    stack, reached = boundary_app(resolved_settings)
    transport = ASGITransport(app=stack, client=(peer, 44321))
    async with AsyncClient(transport=transport, base_url=APP_ORIGIN) as client:
        response = await client.post(PANEL_PATH, headers=header_pairs(headers), content=b'{"key":"x"}')
    return response.status_code, response.text, reached


COOKIE = {"cookie": "access_token=panel-session-token"}


@pytest.mark.asyncio
async def test_the_boundary_refuses_before_the_application_is_called():
    status, body, reached = await boundary_post(
        POLICY_SETTINGS, peer=REMOTE_PEER, headers={**COOKIE, "origin": FOREIGN_ORIGIN}
    )
    assert status == 403
    assert reached == []
    payload = json.loads(body)
    assert payload == {
        "error": CSRF_REJECTION_DETAIL,
        "detail": CSRF_REJECTION_DETAIL,
        "status_code": 403,
        # No request-context middleware in this stack, so there is no id to
        # echo. The boundary reports a fixed null rather than inventing one.
        "request_id": None,
    }
    # The refusal names nothing about the request it refused.
    assert FOREIGN_ORIGIN not in body
    assert "feature-flags" not in body


@pytest.mark.asyncio
async def test_the_refusal_echoes_the_request_context_id_when_there_is_one():
    """The correlation handle the platform's error contract promises.

    Only the request id is per-request, and it is the id the request already has:
    a caller-supplied ``X-Request-ID`` reaches the body only through the single
    ``safe_request_id`` charset rule, so nothing unchecked is reflected.
    """
    scope_id = "abc-123_XYZ"
    assert request_id_for_scope({"state": {"request_id": scope_id}}) == scope_id
    assert json.loads(rejection_body(scope_id))["request_id"] == scope_id
    # Anything outside the safe charset is dropped, not echoed.
    assert request_id_for_scope({"state": {"request_id": "<script>/../"}}) is None
    assert request_id_for_scope({"state": {"request_id": "x" * 65}}) is None
    assert request_id_for_scope({}) is None


@pytest.mark.asyncio
async def test_the_boundary_passes_a_same_origin_mutation_through():
    status, _, reached = await boundary_post(
        POLICY_SETTINGS, peer=REMOTE_PEER, headers={**COOKIE, "origin": APP_ORIGIN}
    )
    assert status == 200
    assert reached == [PANEL_PATH]


@pytest.mark.asyncio
async def test_a_trusted_proxy_https_claim_moves_the_expected_origin():
    proxied = settings(cors_allowed_origins=ALLOWLIST_ORIGIN, trusted_proxy_ips=PROXY_NETWORK)
    headers = {**COOKIE, "x-forwarded-proto": "https"}
    allowed, _, reached = await boundary_post(
        proxied, peer=PROXY_PEER, headers={**headers, "origin": f"https://{APP_HOST}"}
    )
    assert (allowed, reached) == (200, [PANEL_PATH])
    # The browser's own scheme is now the one the proxy reported, so the plain
    # HTTP origin no longer matches.
    refused, _, not_reached = await boundary_post(
        proxied, peer=PROXY_PEER, headers={**headers, "origin": APP_ORIGIN}
    )
    assert (refused, not_reached) == (403, [])


@pytest.mark.asyncio
async def test_the_same_https_claim_from_an_untrusted_peer_changes_nothing():
    proxied = settings(cors_allowed_origins=ALLOWLIST_ORIGIN, trusted_proxy_ips=PROXY_NETWORK)
    headers = {**COOKIE, "x-forwarded-proto": "https", "x-forwarded-host": "attacker.example"}
    refused, _, not_reached = await boundary_post(
        proxied, peer=REMOTE_PEER, headers={**headers, "origin": f"https://{APP_HOST}"}
    )
    assert (refused, not_reached) == (403, [])
    allowed, _, reached = await boundary_post(
        proxied, peer=REMOTE_PEER, headers={**headers, "origin": APP_ORIGIN}
    )
    assert (allowed, reached) == (200, [PANEL_PATH])
