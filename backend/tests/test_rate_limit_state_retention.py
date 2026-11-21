"""Bounded retention and eviction for in-memory rate-limit key state.

Both limiters keyed their client state in a ``defaultdict`` that nothing ever
removed from. That is cheap while ``TRUSTED_PROXY_IPS`` is empty (every request is
the ingress peer) and unbounded the moment the allowlist is configured,
because the keys become real client addresses.

Every test here drives an injected clock instead of sleeping, so retention
boundaries are asserted exactly rather than approximately.
"""

from __future__ import annotations

import app.middleware.security.rate_limit as rate_limit
from app.rate_limit_state_policy import EVICTION_REASON_CAPACITY, EVICTION_REASON_STALE
from app.services.auth_rate_limit import (
    AUTH_LOGIN_SCOPE,
    AUTH_RATE_LIMIT_MAX_ATTEMPTS,
    AUTH_RATE_LIMIT_WINDOW_SECONDS,
    get_auth_rate_limit_state,
    register_auth_failure,
)
from app.services.auth_rate_limit import service as auth_service
from tests.rate_limit_state_retention_support import (  # noqa: F401
    START_TIME,
    _api_status,
    _auth_request,
    _fresh_limiter_state,
    _general_budget,
    clock,
)


def _api_evictions() -> dict[str, int]:
    return dict(rate_limit._BUCKETS.snapshot().evictions)


async def test_stale_client_keys_evict_exactly_at_the_retention_horizon(clock):  # noqa: F811
    """A key survives its whole window and is dropped once it can count nothing."""
    assert await _api_status("198.51.100.10") == 200
    assert await _api_status("198.51.100.20") == 200
    assert len(rate_limit._BUCKETS) == 2

    # Exactly the horizon: `198.51.100.10` could still have a countable timestamp,
    # so admitting a third client must not drop it.
    clock[0] = START_TIME + rate_limit._KEY_RETENTION_SECONDS
    assert await _api_status("198.51.100.30") == 200
    assert len(rate_limit._BUCKETS) == 3
    assert _api_evictions()[EVICTION_REASON_STALE] == 0

    # One tick past the horizon: both t=100 keys are provably dead and go away.
    clock[0] = START_TIME + rate_limit._KEY_RETENTION_SECONDS + 1
    assert await _api_status("198.51.100.40") == 200
    assert len(rate_limit._BUCKETS) == 2
    assert _api_evictions()[EVICTION_REASON_STALE] == 2
    assert _api_evictions()[EVICTION_REASON_CAPACITY] == 0


async def test_an_exhausted_window_keeps_enforcing_across_unrelated_key_churn(clock):  # noqa: F811
    """Retention must not hand a limited client a fresh budget mid-window."""
    budget = _general_budget()
    for _ in range(budget):
        assert await _api_status("198.51.100.10") == 200
    assert await _api_status("198.51.100.10") == 429

    # Half a window later, 256 other clients spend 1000 requests between them.
    clock[0] = START_TIME + rate_limit._KEY_RETENTION_SECONDS // 2
    for index in range(1000):
        assert await _api_status(f"203.0.113.{index % 256}") == 200
    assert await _api_status("198.51.100.10") == 429

    # Its budget starts again when its own window has passed — decided by the
    # window arithmetic, not by the retention pass: the key is still there.
    clock[0] = START_TIME + rate_limit._KEY_RETENTION_SECONDS + 1
    assert await _api_status("198.51.100.10") == 200


async def test_key_count_stays_hard_bounded_while_an_active_client_survives(clock, monkeypatch):  # noqa: F811
    """High-cardinality input cannot grow the store past its configured bound."""
    monkeypatch.setattr(rate_limit._BUCKETS, "capacity_provider", lambda: 8)
    budget = _general_budget()
    for _ in range(budget):
        assert await _api_status("198.51.100.10") == 200
    assert await _api_status("198.51.100.10") == 429

    # 40 distinct addresses inside one window, interleaved with the limited client's
    # own retries — which is what a real client does while it is being throttled.
    for index in range(40):
        assert await _api_status("198.51.100.10") == 429
        assert await _api_status(f"192.0.2.{index}") == 200
        assert len(rate_limit._BUCKETS) <= 8

    assert len(rate_limit._BUCKETS) == 8
    # The actively limited client is the most-recently-active key, so the bound
    # never costs it its enforcement, and the oldest flood keys are gone instead.
    assert await _api_status("198.51.100.10") == 429
    assert _api_evictions()[EVICTION_REASON_CAPACITY] == 33
    assert _api_evictions()[EVICTION_REASON_STALE] == 0


async def test_unverifiable_client_identity_shares_one_fail_closed_key(clock):  # noqa: F811
    """Header text can neither pick a fresh bucket nor inflate cardinality."""
    budget = _general_budget()
    for index in range(budget):
        # No transport peer at all, and a differently forged forwarded chain each
        # time: the peer is not a trusted proxy, so none of it is attribution.
        assert await _api_status(None, forwarded_for=f"198.51.100.{index % 256}") == 200

    assert await _api_status(None, forwarded_for="10.0.0.1") == 429
    assert len(rate_limit._BUCKETS) == 1


def test_auth_failure_windows_evict_when_stale_and_stay_hard_bounded(clock, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auth_service._ATTEMPTS, "capacity_provider", lambda: 4)
    victim = _auth_request("198.51.100.10")
    for _ in range(AUTH_RATE_LIMIT_MAX_ATTEMPTS):
        state = register_auth_failure(AUTH_LOGIN_SCOPE, victim)
    assert state.limited is True
    assert len(auth_service._ATTEMPTS) == 1

    # A flood of distinct addresses inside the window stays inside the bound.
    for index in range(30):
        register_auth_failure(AUTH_LOGIN_SCOPE, _auth_request(f"192.0.2.{index}"))
        assert len(auth_service._ATTEMPTS) <= 4
    assert len(auth_service._ATTEMPTS) == 4
    assert auth_service._ATTEMPTS.snapshot().evictions[EVICTION_REASON_CAPACITY] == 27

    # Still inside the window: the retained windows are still enforcing.
    clock[0] = START_TIME + AUTH_RATE_LIMIT_WINDOW_SECONDS - 1
    assert get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, _auth_request("192.0.2.29")).limited is False
    assert register_auth_failure(AUTH_LOGIN_SCOPE, _auth_request("192.0.2.29")).attempts_used == 2

    # Past the horizon, the next recorded failure sweeps every dead window.
    clock[0] = START_TIME + AUTH_RATE_LIMIT_WINDOW_SECONDS + 2
    register_auth_failure(AUTH_LOGIN_SCOPE, _auth_request("198.51.100.99"))
    assert len(auth_service._ATTEMPTS) == 2  # the t=159 window plus the new one
    assert auth_service._ATTEMPTS.snapshot().evictions[EVICTION_REASON_STALE] == 3


def test_reading_an_auth_window_never_creates_a_key(clock):  # noqa: F811
    state = get_auth_rate_limit_state(AUTH_LOGIN_SCOPE, _auth_request("198.51.100.10"))

    assert state.limited is False
    assert state.attempts_used == 0
    assert state.remaining_attempts == AUTH_RATE_LIMIT_MAX_ATTEMPTS
    assert len(auth_service._ATTEMPTS) == 0


def test_a_finished_auth_window_is_discarded_without_counting_an_eviction(clock):  # noqa: F811
    request = _auth_request("198.51.100.10")
    register_auth_failure(AUTH_LOGIN_SCOPE, request)
    assert len(auth_service._ATTEMPTS) == 1

    auth_service.clear_auth_failures(AUTH_LOGIN_SCOPE, request)

    assert len(auth_service._ATTEMPTS) == 0
    assert auth_service._ATTEMPTS.snapshot().evictions == dict.fromkeys(
        (EVICTION_REASON_STALE, EVICTION_REASON_CAPACITY), 0
    )
    assert auth_service._ATTEMPTS.peek(f"{AUTH_LOGIN_SCOPE}:198.51.100.10") is None
