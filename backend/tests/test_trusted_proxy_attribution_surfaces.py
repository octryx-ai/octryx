"""The surfaces that consume the trusted-proxy decision follow it: the rate-limit key, the API limiter, the auth brute-force bucket and the audit attribution ignore spoofed or padded forwarded headers."""

from __future__ import annotations

import pytest
from starlette.responses import Response

import app.trusted_proxy_policy as boundary
from app.rate_limit_state_policy import BoundedKeyStateStore
from app.services.auth.audit import client_ip_from_request
from app.services.auth_rate_limit import (
    AUTH_LOGIN_SCOPE,
    clear_all_auth_rate_limits,
    register_auth_failure,
)
from app.trusted_proxy_policy import rate_limit_client_key
from tests.trusted_proxy_test_utils import (
    OTHER_CLIENT,
    PADDING,
    PROXY_NETWORK,
    PROXY_PEER,
    REAL_CLIENT,
    REMOTE_PEER,
    padding,
    request,
    settings,
)

# --- Rate-limit attribution -------------------------------------------------


def test_rate_limit_key_ignores_spoofed_forwarded_headers(monkeypatch):
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    rotating = [
        request(peer=REMOTE_PEER, headers={"x-forwarded-for": "192.0.2.1"}),
        request(peer=REMOTE_PEER, headers={"x-forwarded-for": "192.0.2.2"}),
        request(peer=REMOTE_PEER, headers={"x-forwarded-for": "127.0.0.1, 192.0.2.3"}),
    ]
    assert {rate_limit_client_key(built) for built in rotating} == {REMOTE_PEER}


def test_rate_limit_key_separates_real_clients_behind_a_trusted_proxy(monkeypatch):
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    first = request(peer=PROXY_PEER, headers={"x-forwarded-for": REAL_CLIENT})
    second = request(peer=PROXY_PEER, headers={"x-forwarded-for": OTHER_CLIENT})
    assert rate_limit_client_key(first) != rate_limit_client_key(second)
    assert rate_limit_client_key(first) == REAL_CLIENT


def test_rate_limit_key_cannot_be_chosen_by_padding_the_forwarded_chain(monkeypatch):
    """Padding the chain changes neither the bucket nor which address it is."""
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    keys = {
        rate_limit_client_key(
            request(
                peer=PROXY_PEER,
                headers={"x-forwarded-for": ", ".join([*padding(count), REAL_CLIENT])},
            )
        )
        for count in (0, boundary.MAX_FORWARDED_ELEMENTS + 8, boundary.MAX_FORWARDED_ELEMENTS * 4)
    }
    assert keys == {REAL_CLIENT}


def test_rate_limit_key_is_always_a_validated_address(monkeypatch):
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    injected = request(peer=PROXY_PEER, headers={"x-forwarded-for": "a" * 200})
    assert rate_limit_client_key(injected) == PROXY_PEER
    assert rate_limit_client_key(request(peer=None)) == boundary.UNKNOWN_CLIENT_ADDRESS


@pytest.mark.asyncio
async def test_api_rate_limiter_buckets_spoofing_callers_together(monkeypatch):
    """The API limiter must not hand out a fresh window per forged header."""
    from app.middleware.security import rate_limit as api_rate_limit

    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    monkeypatch.delenv("OCTRYX_DISABLE_API_RATE_LIMIT", raising=False)
    # An isolated bounded store, so this assertion depends on nothing that
    # another test left behind and leaves nothing behind itself.
    monkeypatch.setattr(
        api_rate_limit,
        "_BUCKETS",
        BoundedKeyStateStore(
            "test.api.attribution",
            retention_seconds=api_rate_limit._KEY_RETENTION_SECONDS,
            capacity_provider=api_rate_limit._configured_key_capacity,
            new_state=api_rate_limit._RateLimitBucket,
            register=False,
        ),
    )
    monkeypatch.setitem(
        api_rate_limit._API_SCOPES,
        api_rate_limit.API_WRITE_SCOPE,
        api_rate_limit.RateLimitScope(max_requests=2, window_seconds=60, key_prefix="write"),
    )

    async def _ok(_request):
        return Response(status_code=200)

    statuses = []
    for attempt in range(3):
        response = await api_rate_limit.rate_limit_middleware(
            request(
                peer=REMOTE_PEER,
                headers={"x-forwarded-for": f"192.0.2.{attempt + 1}"},
                path="/api/v1/sessions",
            ),
            _ok,
        )
        statuses.append(getattr(response, "status_code", 200))

    assert statuses == [200, 200, 429]


def test_auth_brute_force_bucket_cannot_be_rotated_by_forwarded_headers(monkeypatch):
    """Five failures from one untrusted peer lock out, whatever it claims."""
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    clear_all_auth_rate_limits()
    state = None
    for attempt in range(5):
        state = register_auth_failure(
            AUTH_LOGIN_SCOPE,
            request(peer=REMOTE_PEER, headers={"x-forwarded-for": f"192.0.2.{attempt + 1}"}),
        )
    assert state is not None
    assert state.limited is True
    clear_all_auth_rate_limits()


# --- Audit attribution ------------------------------------------------------


def test_audit_attribution_ignores_untrusted_forwarded_addresses(monkeypatch):
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    spoofed = request(peer=REMOTE_PEER, headers={"x-forwarded-for": REAL_CLIENT})
    assert client_ip_from_request(spoofed) == REMOTE_PEER
    forwarded = request(peer=PROXY_PEER, headers={"x-forwarded-for": REAL_CLIENT})
    assert client_ip_from_request(forwarded) == REAL_CLIENT
    assert client_ip_from_request(None) is None


def test_audit_attribution_cannot_be_chosen_by_padding_the_forwarded_chain(monkeypatch):
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    for header in (
        ", ".join([*PADDING, REAL_CLIENT]),
        ", ".join([*PADDING, REAL_CLIENT, PROXY_PEER]),
    ):
        built = request(peer=PROXY_PEER, headers={"x-forwarded-for": header})
        assert client_ip_from_request(built) == REAL_CLIENT


# --- End-to-end attribution through the real middleware stack ---------------


@pytest.mark.asyncio
async def test_request_audit_records_the_peer_not_the_spoofed_forwarded_address(client, db):
    """The shared harness has no trusted proxy, so the loopback peer wins."""
    from sqlalchemy import select

    from app.models import AuditLog

    action = "POST /api/v1/auth/login"
    await client.post(
        "/api/v1/auth/login",
        json={"username": "no-such-user", "password": "wrong-password"},
        headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"},
    )
    rows = (await db.execute(select(AuditLog.ip_address).where(AuditLog.action == action))).scalars().all()
    assert rows, "audit middleware recorded no row for the request"
    assert set(rows) == {"127.0.0.1"}
