"""Both limiter stores share one validated bound, serialize concurrent admissions and auth failures without losing budget, and export only aggregate metrics."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

import app.middleware.security.rate_limit as rate_limit
from app.config import Settings, get_settings
from app.rate_limit_state_policy import (
    DEFAULT_MAX_RATE_LIMIT_KEYS,
    EVICTION_REASON_CAPACITY,
    EVICTION_REASON_STALE,
    MAX_RATE_LIMIT_KEYS,
    MIN_RATE_LIMIT_KEYS,
    STORE_API,
    STORE_AUTH,
    RateLimitRetentionConfigError,
    state_snapshots,
    validate_max_rate_limit_keys,
)
from app.services.auth_rate_limit import (
    AUTH_LOGIN_SCOPE,
    AUTH_RATE_LIMIT_MAX_ATTEMPTS,
    AUTH_RATE_LIMIT_WINDOW_SECONDS,
    register_auth_failure,
)
from app.services.auth_rate_limit import service as auth_service
from app.services.rate_limit_state_observability import render_rate_limit_state_metrics
from tests.rate_limit_state_retention_support import (  # noqa: F401
    _api_status,
    _auth_request,
    _fresh_limiter_state,
    _general_budget,
    clock,
)


def test_both_limiter_stores_share_one_bounded_policy():
    snapshots = {snapshot.name: snapshot for snapshot in state_snapshots()}
    configured = get_settings().max_rate_limit_keys

    assert {STORE_API, STORE_AUTH} <= set(snapshots)
    assert snapshots[STORE_API].capacity == configured
    assert snapshots[STORE_AUTH].capacity == configured
    assert snapshots[STORE_API].retention_seconds == max(
        scope.window_seconds for scope in rate_limit._API_SCOPES.values()
    )
    assert snapshots[STORE_AUTH].retention_seconds == AUTH_RATE_LIMIT_WINDOW_SECONDS
    for snapshot in snapshots.values():
        assert set(snapshot.evictions) == {EVICTION_REASON_STALE, EVICTION_REASON_CAPACITY}


async def test_concurrent_api_admissions_neither_lose_nor_duplicate_budget(clock):  # noqa: F811
    """Interleaved requests for one key spend exactly one budget, no more, no less."""
    budget = _general_budget()

    statuses = await asyncio.gather(*(_api_status("198.51.100.10") for _ in range(budget * 2)))

    prefix = rate_limit._API_SCOPES[rate_limit.API_GENERAL_SCOPE].key_prefix
    bucket = rate_limit._BUCKETS.peek(f"198.51.100.10:{prefix}")

    assert statuses.count(200) == budget
    assert statuses.count(429) == budget
    assert len(rate_limit._BUCKETS) == 1
    assert bucket is not None
    assert len(bucket.timestamps) == budget


def test_concurrent_auth_failures_are_serialized_without_losing_attempts(clock):  # noqa: F811
    request = _auth_request("198.51.100.10")
    attempts = 80

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: register_auth_failure(AUTH_LOGIN_SCOPE, request), range(attempts)))

    # Every call observed a distinct attempt count, so no append was lost and none
    # was counted twice; `states` is in submission order, not execution order, so
    # the limited/unlimited split is asserted as a count.
    assert len(auth_service._ATTEMPTS) == 1
    assert sorted(state.attempts_used for state in states) == list(range(1, attempts + 1))
    assert sum(1 for state in states if not state.limited) == AUTH_RATE_LIMIT_MAX_ATTEMPTS - 1


@pytest.mark.parametrize("value", [MIN_RATE_LIMIT_KEYS - 1, MAX_RATE_LIMIT_KEYS + 1, 0, -1])
def test_a_bound_that_would_not_bound_fails_startup(value):
    with pytest.raises(RateLimitRetentionConfigError):
        validate_max_rate_limit_keys(value)
    with pytest.raises(ValidationError):
        Settings(debug=True, runtime_profile="local", max_rate_limit_keys=value)


@pytest.mark.parametrize("value", [True, 1000.0, "20000", None])
def test_a_non_integer_bound_is_rejected_rather_than_coerced(value):
    with pytest.raises(RateLimitRetentionConfigError):
        validate_max_rate_limit_keys(value)


def test_the_default_bound_is_valid_and_is_what_the_limiters_use():
    assert validate_max_rate_limit_keys(DEFAULT_MAX_RATE_LIMIT_KEYS) == DEFAULT_MAX_RATE_LIMIT_KEYS
    assert Settings(debug=True, runtime_profile="local").max_rate_limit_keys == DEFAULT_MAX_RATE_LIMIT_KEYS
    assert rate_limit._configured_key_capacity() == get_settings().max_rate_limit_keys
    assert auth_service._configured_key_capacity() == get_settings().max_rate_limit_keys


async def test_exported_metrics_are_aggregates_and_carry_no_client_identity(clock):  # noqa: F811
    assert await _api_status("198.51.100.77") == 200
    register_auth_failure(AUTH_LOGIN_SCOPE, _auth_request("198.51.100.88"))

    rendered = "\n".join(render_rate_limit_state_metrics())

    assert f'octryx_rate_limit_tracked_keys{{store="{STORE_API}"}} 1' in rendered
    assert f'octryx_rate_limit_tracked_keys{{store="{STORE_AUTH}"}} 1' in rendered
    assert f'octryx_rate_limit_key_capacity{{store="{STORE_API}"}} ' in rendered
    for store in (STORE_API, STORE_AUTH):
        for reason in (EVICTION_REASON_STALE, EVICTION_REASON_CAPACITY):
            assert f'octryx_rate_limit_key_evictions_total{{store="{store}",reason="{reason}"}} 0' in rendered
    assert "198.51.100.77" not in rendered
    assert "198.51.100.88" not in rendered
