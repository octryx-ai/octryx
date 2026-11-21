from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.models import IdentityProvider
from app.services.oidc_provider_config import build_authorization_url, resolve_provider_endpoints


def test_resolve_provider_endpoints_prefers_provider_values_and_trims_whitespace() -> None:
    provider = IdentityProvider(
        authorization_endpoint="  https://provider.example.com/auth  ",
        token_endpoint=None,
        userinfo_endpoint="",
        client_id="  client-123  ",
    )

    endpoints = resolve_provider_endpoints(
        provider,
        {
            "authorization_endpoint": "https://discovery.example.com/auth",
            "token_endpoint": " https://discovery.example.com/token ",
            "userinfo_endpoint": "https://discovery.example.com/userinfo",
        },
    )

    assert endpoints.authorization_endpoint == "https://provider.example.com/auth"
    assert endpoints.token_endpoint == "https://discovery.example.com/token"
    assert endpoints.userinfo_endpoint == "https://discovery.example.com/userinfo"


def test_resolve_provider_endpoints_requires_authorization_configuration() -> None:
    provider = IdentityProvider(provider_type="oidc", client_id=" ")

    with pytest.raises(HTTPException) as exc_info:
        resolve_provider_endpoints(provider, {}, require_authorization=True)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Identity provider is missing authorization configuration"


def test_resolve_provider_endpoints_requires_token_and_userinfo_endpoints() -> None:
    provider = IdentityProvider(provider_type="oidc", client_id="client-123")

    with pytest.raises(HTTPException) as exc_info:
        resolve_provider_endpoints(
            provider,
            {"token_endpoint": "https://issuer.example.com/token"},
            require_token_userinfo=True,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Identity provider is missing token or userinfo endpoint"


def test_build_authorization_url_uses_expected_request_parameters() -> None:
    url = build_authorization_url(
        authorization_endpoint="https://issuer.example.com/auth",
        client_id="client-123",
        redirect_uri="https://app.example.com/api/v1/auth/oidc/callback",
        scopes=["openid", "profile", "email", "groups"],
        state="state-token",
        nonce="nonce-token",
        code_challenge="challenge-token",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "issuer.example.com"
    assert parsed.path == "/auth"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["https://app.example.com/api/v1/auth/oidc/callback"]
    assert params["scope"] == ["openid profile email groups"]
    assert params["state"] == ["state-token"]
    assert params["nonce"] == ["nonce-token"]
    assert params["code_challenge"] == ["challenge-token"]
    assert params["code_challenge_method"] == ["S256"]
