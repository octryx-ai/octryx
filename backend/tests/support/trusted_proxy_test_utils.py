"""Shared fixtures for the trusted-proxy boundary suites."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

import app.trusted_proxy_policy as boundary
from app.config import Settings
from app.middleware.security.trusted_proxy import TrustedProxyBoundaryMiddleware
from app.trusted_proxy_policy import ClientIdentity, resolve_client_identity

PROXY_PEER = "10.1.2.3"
SECOND_PROXY_PEER = "10.1.2.4"
REMOTE_PEER = "203.0.113.5"
REAL_CLIENT = "198.51.100.7"
OTHER_CLIENT = "198.51.100.8"
PROXY_NETWORK = "10.0.0.0/8"

# A production-like profile for the startup-reporting checks.
PRODUCTION_LIKE = {"runtime_profile": "production", "database_url": "postgresql+asyncpg://oe:pw@db:5432/oe"}

HeaderInput = Mapping[str, str] | Sequence[tuple[str, str]] | None


def settings(**overrides) -> Settings:
    values: dict[str, object] = {
        "debug": False,
        "runtime_profile": "local",
        "jwt_secret": "s" * 48,
        "encryption_key": "e" * 32,
        "admin_default_password": "S3cureAdminPass!",
        "admin_email": "admin@octryx.local",
        "cors_allowed_origins": "https://octryx.example",
        "force_secure_auth_cookies": True,
        "trusted_proxy_ips": "",
    }
    values.update(overrides)
    return Settings(**values)


def header_pairs(headers: HeaderInput) -> list[tuple[str, str]]:
    if headers is None:
        return []
    if isinstance(headers, Mapping):
        return list(headers.items())
    return [(name, value) for name, value in headers]


def request(
    *,
    peer: str | None = REMOTE_PEER,
    scheme: str = "http",
    headers: HeaderInput = None,
    path: str = "/api/v1/auth/login",
) -> Request:
    raw_headers = [(b"host", b"octryx.example")]
    raw_headers += [(name.lower().encode(), value.encode()) for name, value in header_pairs(headers)]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": scheme,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw_headers,
            "client": (peer, 44321) if peer else None,
            "server": ("octryx.example", 80),
        }
    )


def identity(built_request: Request, resolved_settings: Settings) -> ClientIdentity:
    return resolve_client_identity(
        peer_address=built_request.client.host if built_request.client else None,
        transport_scheme=built_request.url.scheme,
        headers=built_request.headers,
        settings=resolved_settings,
    )


def padding(count: int) -> list[str]:
    return [f"192.0.2.{index % 250 + 1}" for index in range(count)]


PADDING = padding(boundary.MAX_FORWARDED_ELEMENTS + 8)


def boundary_app(resolved_settings: Settings):
    async def echo(scope, receive, send):
        recorded = scope["state"][boundary.SCOPE_STATE_KEY]
        body = (
            f'{{"client":"{scope["client"][0]}","scheme":"{scope["scheme"]}",'
            f'"peer":"{recorded.peer_address}","trusted":{str(recorded.via_trusted_proxy).lower()}}}'
        )
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body.encode()})

    return TrustedProxyBoundaryMiddleware(echo, settings=resolved_settings)


async def boundary_get(resolved_settings: Settings, *, peer: str, headers: HeaderInput) -> dict:
    transport = ASGITransport(app=boundary_app(resolved_settings), client=(peer, 44321))
    async with AsyncClient(transport=transport, base_url="http://octryx.example") as client:
        response = await client.get("/api/v1/health", headers=header_pairs(headers))
    return response.json()
