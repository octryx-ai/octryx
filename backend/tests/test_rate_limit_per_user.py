"""Contract: authenticated traffic is limited per user, safe reads only by a runaway guard.

The limiter runs in front of a small app (and, for volume, is called directly with real requests): a verified
platform session token or platform OAuth token gets its own per-user bucket (``user_read`` 3000/min,
``user_write`` 600/min); everything else, including a forged or expired token, keeps the per-address scopes;
``/api/v1/auth/*`` stays per address; every static mount and page shell is exempt; limits come from Settings
(env overrides); a 429 names its scope. The password login is limited per address and per username.
"""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient

import app.middleware.security.rate_limit as rate_limit
from app.config import get_settings
from app.services.auth import create_access_token
from app.services.oauth_provider.tokens import mint_access_token
from tests.rate_limit_per_user_support import IP, _call, _fresh, _request, _settings_env, _statuses  # noqa: F401


def _oauth(user_id: str, grant_id: str) -> str:
    return mint_access_token(user_id=user_id, client_id="c", grant_id=grant_id, scopes=["mcp"], resource=None)[0]


def _forged() -> str:
    return jwt.encode({"sub": "victim", "aud": "octryx-api", "iss": "octryx-backend"},
                      "not-the-secret-not-the-secret-not-the-secret", algorithm="HS256")


def _foreign_issuer() -> str:
    """The right secret, but neither the platform's nor the OAuth server's issuer."""
    claims = {"sub": "victim", "grant_id": "g", "iss": "another-issuer", "exp": 4102444800}
    return jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def app_client(tmp_path):
    (tmp_path / "a.js").write_text("export {};\n", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/things")
    async def _things():
        return {"ok": True}

    @app.get("/chat")
    async def _shell():
        return Response("<html></html>", media_type="text/html")

    app.mount("/chat/static", StaticFiles(directory=str(tmp_path)), name="chat-static")
    app.mount("/admin/static", StaticFiles(directory=str(tmp_path)), name="admin-static")
    app.middleware("http")(rate_limit.rate_limit_middleware)
    transport = ASGITransport(app=app, client=(IP, 40000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# --- per-user buckets -----------------------------------------------------------------------------------


async def test_one_user_reading_1000_times_a_minute_is_never_limited_and_3001_meets_the_guard():
    token = create_access_token("user-a")
    assert set(await _statuses(1000, token=token)) == {200}
    assert set(await _statuses(2000, token=token)) == {200}
    limited = await _call(_request(token=token))
    assert limited.status_code == 429
    body = limited.body.decode()
    assert '"code":"rate_limit_user_read"' in body and '"scope":"user_read"' in body
    assert limited.headers["X-RateLimit-Limit"] == "3000" and limited.headers["X-RateLimit-Remaining"] == "0"
    assert int(limited.headers["Retry-After"]) >= 1 and limited.headers["X-RateLimit-Window"] == "60"


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_every_safe_method_of_a_user_is_a_read(method):
    response = await _call(_request(method, token=create_access_token("user-a")))
    assert response.headers["X-RateLimit-Scope"] == "user_read"


async def test_users_behind_one_address_each_have_their_own_write_bucket():
    alice, bob = create_access_token("alice"), create_access_token("bob")
    assert set(await _statuses(600, method="POST", token=alice)) == {200}
    refused = await _call(_request("POST", token=alice))
    assert refused.status_code == 429 and b"rate_limit_user_write" in refused.body
    assert (await _call(_request("POST", token=bob))).status_code == 200, "bob is not affected"
    assert (await _call(_request("GET", token=alice))).status_code == 200, "reads are a separate guard"
    assert (await _call(_request("POST"))).status_code == 200, "anonymous traffic of the address is separate"


async def test_the_session_cookie_identifies_the_user_too():
    response = await _call(_request(cookie=create_access_token("cookie-user")))
    assert response.headers["X-RateLimit-Scope"] == "user_read"


async def test_each_oauth_grant_has_its_own_bucket(monkeypatch):
    _settings_env(monkeypatch, rate_limit_user_read_per_min=2)
    first, second = _oauth("mcp-user", "grant-1"), _oauth("mcp-user", "grant-2")
    assert await _statuses(3, token=first) == [200, 200, 429]
    assert (await _call(_request(token=second))).status_code == 200


async def test_heavy_and_gateway_scopes_are_per_user():
    alice, bob = create_access_token("alice"), create_access_token("bob")
    assert set(await _statuses(30, method="POST", path="/api/v1/tasks/reload", token=alice)) == {200}
    refused = await _call(_request("POST", "/api/v1/tasks/reload", token=alice))
    assert refused.status_code == 429 and b"rate_limit_heavy" in refused.body
    assert (await _call(_request("POST", "/api/v1/tasks/reload", token=bob))).status_code == 200
    gateway = await _call(_request("POST", "/api/v1/agent-gateway/hooks", token=alice))
    assert gateway.headers["X-RateLimit-Scope"] == "agent_gateway" and gateway.headers["X-RateLimit-Limit"] == "600"


# --- anonymous, forged, expired ---------------------------------------------------------------------------


async def test_anonymous_traffic_stays_per_address():
    assert set(await _statuses(120)) == {200}
    refused = await _call(_request())
    assert refused.status_code == 429 and b"rate_limit_ip_general" in refused.body
    assert (await _call(_request(ip="203.0.113.8"))).status_code == 200, "another address has its own budget"
    assert set(await _statuses(30, method="POST")) == {200}
    write = await _call(_request("POST"))
    assert write.status_code == 429 and b"rate_limit_ip_write" in write.body


@pytest.mark.parametrize("token", [
    pytest.param(lambda: create_access_token("someone", expires_delta=timedelta(minutes=-5)), id="expired"),
    pytest.param(_forged, id="forged"),
    pytest.param(_foreign_issuer, id="foreign-issuer"),
    pytest.param(lambda: "oek_not-a-jwt-api-key", id="api-key"),
    pytest.param(lambda: "x" * 9000, id="oversized"),
])
async def test_a_token_that_does_not_verify_gets_the_address_bucket_never_a_fresh_one(token):
    assert set(await _statuses(120)) == {200}  # the address's anonymous budget is spent
    refused = await _call(_request(token=token()))
    assert refused.status_code == 429 and b"rate_limit_ip_general" in refused.body


async def test_the_seat_bearer_is_never_decoded_as_a_user():
    response = await _call(_request("POST", "/api/v1/model-gateway/anthropic/seat/v1/messages",
                                    token=create_access_token("alice")))
    assert response.headers["X-RateLimit-Scope"] == "agent_gateway"
    assert all(not key.startswith("user:") for key in rate_limit._USER_BUCKETS._entries)


async def test_the_auth_scope_stays_per_address_even_with_a_valid_token():
    token = create_access_token("alice")
    assert set(await _statuses(20, method="POST", path="/api/v1/auth/refresh", token=token)) == {200}
    refused = await _call(_request("POST", "/api/v1/auth/refresh", token=create_access_token("bob")))
    assert refused.status_code == 429 and b"rate_limit_auth" in refused.body


# --- exemptions -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "exempt"), [
    ("GET", "/admin/static/chat/assets/a.js", True),
    ("GET", "/chat/static/chat/assets/a.css", True),
    ("HEAD", "/chat/static/chat/favicon.svg", True),
    ("GET", "/chat", True),
    ("GET", "/chat/", True),
    ("GET", "/admin", True),
    ("GET", "/admin/chat", True),
    ("GET", "/admin/settings", True),
    ("GET", "/admin/control-plane", True),
    ("HEAD", "/chat", True),
    ("POST", "/chat", False),
    ("POST", "/chat/static/chat/a.js", False),
    ("GET", "/chat/api", False),
    ("GET", "/chat/api/bootstrap", False),
    ("GET", "/admin/chat/api/panel/projects", False),
    ("GET", "/admin/static", False),
    ("GET", "/api/v1/agent-board/action-needed", False),
])
def test_static_mounts_and_page_shells_are_exempt_for_safe_reads(method, path, exempt):
    assert rate_limit._should_exempt(_request(method, path)) is exempt


async def test_page_loads_and_assets_load_after_the_address_budget_is_spent(app_client):
    for _ in range(120):
        assert (await app_client.get("/api/v1/things")).status_code == 200
    assert (await app_client.get("/api/v1/things")).status_code == 429
    for _ in range(200):
        assert (await app_client.get("/chat/static/a.js")).status_code == 200
        assert (await app_client.get("/admin/static/a.js")).status_code == 200
    shell = await app_client.get("/chat")
    assert shell.status_code == 200 and "x-ratelimit-limit" not in shell.headers
    user = await app_client.get("/api/v1/things", headers={"Authorization": f"Bearer {create_access_token('u')}"})
    assert user.status_code == 200, "a signed-in user behind the spent address keeps working"
