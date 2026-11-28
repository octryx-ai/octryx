"""The API rate limiter must not throttle the SPA code mounts."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.routing import Match, Mount

import app.middleware.security.rate_limit as rate_limit
from app.http_setup import configure_http

CHUNK = "/admin/static/chat/assets/AdminRuntimesTab-test.js"
API_READ = "/admin/chat/api/panel/runtimes"


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


@pytest.fixture(autouse=True)
def _limiter_enabled_with_fresh_buckets(monkeypatch):
    monkeypatch.delenv("OCTRYX_DISABLE_API_RATE_LIMIT", raising=False)
    rate_limit.clear_rate_limit_buckets()
    yield
    rate_limit.clear_rate_limit_buckets()


@pytest.fixture
def static_dir(tmp_path):
    assets = tmp_path / "chat" / "assets"
    assets.mkdir(parents=True)
    (assets / "AdminRuntimesTab-test.js").write_text("export const AdminRuntimesTab = null;\n", encoding="utf-8")
    (tmp_path / "chat" / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture
async def client(static_dir):
    app = FastAPI()

    @app.get(API_READ)
    async def _runtimes():
        return []

    app.mount("/chat/static", StaticFiles(directory=str(static_dir)), name="chat-static")
    app.mount("/admin/static", StaticFiles(directory=str(static_dir)), name="admin-static")
    app.middleware("http")(rate_limit.rate_limit_middleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client


def _budget(scope: str) -> int:
    return rate_limit._API_SCOPES[scope].max_requests


@pytest.mark.parametrize(
    ("method", "path", "exempt"),
    [
        ("GET", CHUNK, True),
        ("HEAD", "/admin/static/chat/favicon.svg", True),
        ("POST", CHUNK, False),
        ("PUT", CHUNK, False),
        ("PATCH", CHUNK, False),
        ("DELETE", CHUNK, False),
        ("OPTIONS", CHUNK, False),
        ("GET", "/admin/static", False),
        ("GET", "/admin/staticfiles/chat/assets/x.js", False),
        ("GET", "/chat/static/chat/favicon.svg", True),
        ("GET", API_READ, False),
        ("GET", "/healthz", True),
    ],
)
def test_only_safe_reads_of_the_spa_code_mount_are_exempt(method, path, exempt):
    assert rate_limit._should_exempt(_request(method, path)) is exempt


async def test_spa_code_reads_do_not_spend_the_api_budget(client):
    for _ in range(_budget(rate_limit.API_GENERAL_SCOPE) + 5):
        assert (await client.get(CHUNK)).status_code == 200

    first_api_read = await client.get(API_READ)
    assert first_api_read.status_code == 200
    assert first_api_read.headers["x-ratelimit-remaining"] == str(_budget(rate_limit.API_GENERAL_SCOPE) - 1)


async def test_lazy_chunk_still_loads_after_the_api_budget_is_spent(client):
    for _ in range(_budget(rate_limit.API_GENERAL_SCOPE)):
        assert (await client.get(API_READ)).status_code == 200
    assert (await client.get(API_READ)).status_code == 429

    chunk = await client.get(CHUNK)
    assert chunk.status_code == 200
    assert "javascript" in chunk.headers["content-type"]
    assert "x-ratelimit-limit" not in chunk.headers
    assert (await client.head(CHUNK)).status_code == 200
    # `/chat/static` serves the same build and is exempt too (its request metrics may still be recorded).
    assert (await client.get("/chat/static/chat/favicon.svg")).status_code == 200


async def test_non_read_methods_on_the_spa_code_mount_stay_limited(client):
    statuses = [(await client.post(CHUNK)).status_code for _ in range(_budget(rate_limit.API_WRITE_SCOPE) + 1)]

    assert statuses[:-1] == [405] * _budget(rate_limit.API_WRITE_SCOPE)
    assert statuses[-1] == 429


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("prefix", ["/admin/static/", "/chat/static/"])
def test_only_the_static_mount_serves_the_exempt_prefix(tmp_path, method, prefix):
    # Drift guard on the production wiring: a route or mount added under the exempt
    # prefix would be served without the API limiter.
    app = FastAPI()
    configure_http(app, static_dir=tmp_path)
    path = f"{prefix}chat/assets/x.js"
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": [], "query_string": b""}

    candidates = [route for route in app.router.routes if route.matches(scope)[0] is not Match.NONE]

    assert len(candidates) == 1
    (route,) = candidates
    assert isinstance(route, Mount)
    assert route.path + "/" == prefix and prefix in rate_limit._STATIC_ASSET_MOUNT_PREFIXES
    assert isinstance(route.app, StaticFiles)


def test_every_static_mount_of_the_app_is_exempt(tmp_path):
    app = FastAPI()
    configure_http(app, static_dir=tmp_path)
    mounts = {route.path + "/" for route in app.router.routes if isinstance(route, Mount)
              and isinstance(route.app, StaticFiles)}
    assert mounts and mounts <= set(rate_limit._STATIC_ASSET_MOUNT_PREFIXES)
