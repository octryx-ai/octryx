"""OIDC provider configuration and authorization request helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from ..models import IdentityProvider


@dataclass(frozen=True)
class OidcProviderEndpoints:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str


def _normalized_endpoint(provider_value: Any, config: dict[str, Any], key: str) -> str:
    return str(provider_value or config.get(key) or "").strip()


def resolve_provider_endpoints(
    provider: IdentityProvider,
    config: dict[str, Any],
    *,
    require_authorization: bool = False,
    require_token_userinfo: bool = False,
) -> OidcProviderEndpoints:
    authorization_endpoint = _normalized_endpoint(provider.authorization_endpoint, config, "authorization_endpoint")
    token_endpoint = _normalized_endpoint(provider.token_endpoint, config, "token_endpoint")
    userinfo_endpoint = _normalized_endpoint(provider.userinfo_endpoint, config, "userinfo_endpoint")

    if require_authorization and (not authorization_endpoint or not str(provider.client_id or "").strip()):
        raise HTTPException(status_code=400, detail="Identity provider is missing authorization configuration")
    if require_token_userinfo and (not token_endpoint or not userinfo_endpoint):
        raise HTTPException(status_code=400, detail="Identity provider is missing token or userinfo endpoint")

    return OidcProviderEndpoints(
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        userinfo_endpoint=userinfo_endpoint,
    )


def build_authorization_url(
    *,
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"
