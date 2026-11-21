"""Every channel webhook route refuses an unauthenticated post before any work, the development exception is refused outside debug, and signing keys are cached, refreshed rarely and taken only from the issuer's host."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.main import app
from tests.channel_webhook_auth_support import BF_JWK, _code, _post, channels  # noqa: F401


def _channel_webhook_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and "POST" in route.methods
        and route.path.startswith(("/api/v1/channels", "/api/v1/teams/calls"))
    ]


@pytest.mark.asyncio
async def test_every_channel_webhook_route_refuses_an_unauthenticated_post_before_any_work(client, channels):  # noqa: F811
    routes = _channel_webhook_routes()
    paths = {route.path for route in routes}
    assert {
        "/api/v1/channels/{channel_id}/webhook",
        "/api/v1/channels/msteams/{channel_id}/webhook",
        "/api/v1/channels/slack/{channel_id}/webhook",
        "/api/v1/teams/calls/incoming-call",
    } <= paths
    channel_for = {"/api/v1/channels/slack/{channel_id}/webhook": "902"}
    for route in routes:
        url = route.path.replace("{channel_id}", channel_for.get(route.path, "901"))
        if route.path.endswith("/incoming-call"):
            url += "?call_id=call-9&channel_id=901&project_id=p"
        # Not JSON: a route that parsed before authenticating would fail differently.
        response = await _post(client, url, b"{not json")
        assert response.status_code in (401, 403), route.path
        assert _code(response) in {"channel_webhook_unauthenticated", "channel_webhook_auth_not_configured"}, route.path
    assert all(recorder.payloads == [] for recorder in channels["recorders"].values())


def test_the_development_exception_is_refused_outside_debug():
    from app.config import Settings

    production_like = {
        "jwt_secret": "x" * 48,
        "encryption_key": "y" * 48,
        "admin_default_password": "S3cureAdminPass!",
        "admin_email": "admin@octryx.local",
        "cors_allowed_origins": "http://localhost:5173",
        "runtime_profile": "local",
        "force_secure_auth_cookies": True,
    }
    with pytest.raises(ValidationError, match="Unauthenticated channel webhooks are development-only"):
        Settings(debug=False, channel_webhook_dev_unauthenticated=True, **production_like)
    assert Settings(
        debug=True, channel_webhook_dev_unauthenticated=True, **production_like
    ).channel_webhook_dev_unauthenticated


@pytest.mark.asyncio
async def test_signing_keys_are_cached_refreshed_rarely_and_only_taken_from_the_issuers_host():
    from app.services.channel_webhook_auth.signing_keys import OpenIdSigningKeySource, SigningKeysUnavailableError

    openid_url = "https://login.botframework.com/v1/.well-known/openidconfiguration"
    documents = {
        openid_url: {"jwks_uri": "https://login.botframework.com/v1/.well-known/keys"},
        "https://login.botframework.com/v1/.well-known/keys": {"keys": [BF_JWK]},
    }
    fetched: list[str] = []
    clock = [1000.0]

    async def fetch(url: str):
        fetched.append(url)
        return documents[url]

    hosts = frozenset({"login.botframework.com"})
    source = OpenIdSigningKeySource(openid_url, jwks_hosts=hosts, fetch_json=fetch, clock=lambda: clock[0])
    assert await source.keys() == [BF_JWK]
    assert await source.keys() == [BF_JWK]
    assert await source.keys(refresh=True) == [BF_JWK]  # an unknown kid right away: no refetch
    assert len(fetched) == 2
    clock[0] += 301
    await source.keys(refresh=True)
    assert len(fetched) == 4

    documents[openid_url] = {"jwks_uri": "https://keys.attacker.example/keys"}
    moved = OpenIdSigningKeySource(openid_url, jwks_hosts=hosts, fetch_json=fetch)
    with pytest.raises(SigningKeysUnavailableError, match="jwks_uri_not_allowed"):
        await moved.keys()
    assert "https://keys.attacker.example/keys" not in fetched
