"""Shared helpers for the test_rate_limit_per_user_* modules."""

from __future__ import annotations

import pytest
from fastapi import Response
from starlette.requests import Request

import app.middleware.security.rate_limit as rate_limit
from app.config import get_settings
from app.services.auth_rate_limit import clear_all_auth_rate_limits

IP = "203.0.113.7"


def _settings_env(monkeypatch, **values: int) -> None:
    for name, value in values.items():
        monkeypatch.setenv(f"OCTRYX_{name.upper()}", str(value))
    get_settings.cache_clear()


def _request(method: str = "GET", path: str = "/api/v1/things", *, token: str | None = None, ip: str = IP,
             cookie: str | None = None) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if cookie:
        headers.append((b"cookie", f"access_token={cookie}".encode()))
    return Request({"type": "http", "method": method, "path": path, "query_string": b"", "headers": headers,
                    "client": (ip, 40000), "server": ("testserver", 80), "scheme": "http"})


async def _ok(_request):
    return Response(status_code=200)


async def _call(request: Request) -> Response:
    return await rate_limit.rate_limit_middleware(request, _ok)


async def _statuses(count: int, **kwargs) -> list[int]:
    return [(await _call(_request(**kwargs))).status_code for _ in range(count)]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("OCTRYX_DISABLE_API_RATE_LIMIT", raising=False)
    get_settings.cache_clear()
    rate_limit.clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    yield
    rate_limit.clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    get_settings.cache_clear()
