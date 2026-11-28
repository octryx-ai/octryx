"""Calls to the identity provider: discovery, code exchange, userinfo, and the stored client secret."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityProvider
from ..secret import get_secret_value


async def _provider_client_secret(db: AsyncSession, provider: IdentityProvider) -> str | None:
    if not provider.client_secret_secret_ref:
        return None
    return await get_secret_value(db, secret_id=provider.client_secret_secret_ref, purpose="oidc.sign_in")


async def _discover_provider_configuration(provider: IdentityProvider) -> dict[str, Any]:
    discovery_url = str(provider.discovery_url or "").strip()
    issuer_url = str(provider.issuer_url or "").strip().rstrip("/")
    explicit = all(
        str(value or "").strip()
        for value in (provider.authorization_endpoint, provider.token_endpoint, provider.jwks_uri)
    )
    if not discovery_url and explicit:
        # Split horizon (e.g. IdP): the issuer name is not resolvable from here, and every endpoint is set.
        return {}
    if not discovery_url and issuer_url:
        discovery_url = f"{issuer_url}/.well-known/openid-configuration"
    if not discovery_url:
        return {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(discovery_url)
        response.raise_for_status()
        return response.json()


async def _exchange_authorization_code(
    *,
    provider: IdentityProvider,
    token_endpoint: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "client_id": provider.client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            token_endpoint,
            data=payload,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


async def _fetch_userinfo_claims(userinfo_endpoint: str, access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
