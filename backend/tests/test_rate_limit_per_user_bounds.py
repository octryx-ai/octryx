"""Every limit honours its environment override and refuses a value below one, no number of addresses can evict a user's bucket, and failed logins are limited per address and per username before the address limit."""

from __future__ import annotations

import pytest

import app.middleware.security.rate_limit as rate_limit
from app.services.auth import create_access_token
from app.services.auth_rate_limit import login as login_limit
from tests.rate_limit_per_user_support import _call, _fresh, _request, _settings_env, _statuses  # noqa: F401

# --- settings and bounded state ---------------------------------------------------------------------------


async def test_every_limit_honours_its_env_override(monkeypatch):
    _settings_env(monkeypatch, rate_limit_user_read_per_min=3, rate_limit_user_write_per_min=2,
                  rate_limit_ip_general_per_min=4, rate_limit_ip_write_per_min=1, rate_limit_auth_per_min=2)
    token = create_access_token("alice")
    assert await _statuses(4, token=token) == [200, 200, 200, 429]
    assert await _statuses(3, method="POST", token=token) == [200, 200, 429]
    assert await _statuses(5) == [200, 200, 200, 200, 429]
    assert await _statuses(2, method="POST") == [200, 429]
    assert await _statuses(3, method="POST", path="/api/v1/auth/login", ip="198.51.100.1") == [200, 200, 429]


def test_a_limit_below_one_fails_settings(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("OCTRYX_RATE_LIMIT_USER_READ_PER_MIN", "0")
    with pytest.raises((ValidationError, Exception)):
        Settings()


async def test_no_number_of_addresses_can_evict_a_users_bucket(monkeypatch):
    _settings_env(monkeypatch, max_rate_limit_keys=256, rate_limit_user_write_per_min=5)
    token = create_access_token("alice")
    assert await _statuses(5, method="POST", token=token) == [200] * 5
    for index in range(600):  # far more distinct addresses than the bound
        await _call(_request(ip=f"10.1.{index // 250}.{index % 250}"))
    assert (await _call(_request("POST", token=token))).status_code == 429, "alice's window was not reset"
    assert len(rate_limit._BUCKETS) <= 256


# --- login brute force ------------------------------------------------------------------------------------


def test_failed_logins_are_limited_per_address():
    request = _request("POST", "/api/v1/auth/login")
    for index in range(5):
        login_limit.register_failure(request, f"name-{index}")
    assert login_limit.state(request, "fresh-name").limited is True


def test_failed_logins_are_limited_per_username_from_any_address(monkeypatch):
    _settings_env(monkeypatch, rate_limit_login_failures_per_username=3)
    for index in range(3):
        login_limit.register_failure(_request("POST", "/api/v1/auth/login", ip=f"192.0.2.{index + 1}"), "Admin ")
    fresh_address = _request("POST", "/api/v1/auth/login", ip="192.0.2.99")
    assert login_limit.state(fresh_address, "admin").limited is True, "normalized: case and padding"
    assert login_limit.state(fresh_address, "other").limited is False
    login_limit.clear(fresh_address, "admin")
    assert login_limit.state(fresh_address, "admin").limited is False


async def test_the_login_route_refuses_a_username_before_the_address_limit(client, monkeypatch):
    _settings_env(monkeypatch, rate_limit_login_failures_per_username=3)
    for _ in range(3):
        failed = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "wrong"})
        assert failed.status_code == 401
    # The address has 3 of its 5 failures: only the username's window refuses.
    blocked = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "wrong"})
    assert blocked.status_code == 429
    other = await client.post("/api/v1/auth/login", data={"username": "someone-else", "password": "wrong"})
    assert other.status_code == 401


async def test_the_web_login_form_refuses_a_username_before_the_address_limit(client, monkeypatch):
    _settings_env(monkeypatch, rate_limit_login_failures_per_username=2)
    origin = {"origin": "http://test"}
    for _ in range(2):
        failed = await client.post("/admin/login", data={"username": "admin", "password": "wrong"}, headers=origin)
        assert failed.status_code == 401
    blocked = await client.post("/admin/login", data={"username": "admin", "password": "wrong"}, headers=origin)
    assert blocked.status_code == 429
    other = await client.post("/admin/login", data={"username": "someone-else", "password": "wrong"}, headers=origin)
    assert other.status_code == 401
