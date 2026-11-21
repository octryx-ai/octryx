"""Shared helpers for the test_rate_limit_state_retention_* modules."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

import app.middleware.security.rate_limit as rate_limit
from app.services.auth_rate_limit import clear_all_auth_rate_limits
from app.services.auth_rate_limit import service as auth_service

START_TIME = 100.0


API_PATH = "/api/v1/chat/bootstrap"


@pytest.fixture
def clock(monkeypatch) -> list[float]:
    """One injected monotonic reading shared by both limiters."""
    reading = [START_TIME]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: reading[0])
    monkeypatch.setattr(auth_service, "monotonic", lambda: reading[0])
    return reading


def _api_request(client_host: str | None, *, forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": API_PATH,
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "scheme": "http",
    }
    if client_host is not None:
        scope["client"] = (client_host, 12345)
    return Request(scope)


async def _api_status(client_host: str | None, *, forwarded_for: str | None = None) -> int:
    async def _call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = await rate_limit.rate_limit_middleware(
        _api_request(client_host, forwarded_for=forwarded_for), _call_next
    )
    return response.status_code


def _auth_request(client_host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "query_string": b"",
            "headers": [],
            "client": (client_host, 12345),
        }
    )


def _general_budget() -> int:
    return rate_limit._API_SCOPES[rate_limit.API_GENERAL_SCOPE].max_requests


@pytest.fixture(autouse=True)
def _fresh_limiter_state(monkeypatch):
    monkeypatch.delenv("OCTRYX_DISABLE_API_RATE_LIMIT", raising=False)
    rate_limit.clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    yield
    rate_limit.clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
