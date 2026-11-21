"""Refresh-token exchange for a connected Google Gemini provider."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityProvider, LLMProvider
from ..control_plane.provider_auth import provider_secret_scope
from ..oidc import _discover_provider_configuration, _provider_client_secret
from ..provider.oauth_config_bridge import read_oauth_metadata


async def build_google_access_token(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    get_secret_value_func,
) -> tuple[str, str]:
    meta = await read_oauth_metadata(db, provider)
    identity_provider_id = str(meta.get("oauth_identity_provider_id") or "").strip()
    project_id = str(meta.get("google_cloud_project") or "").strip()
    if not identity_provider_id or not project_id:
        raise RuntimeError("Google OAuth provider is missing identity provider linkage or project")
    identity_provider = await db.get(IdentityProvider, identity_provider_id)
    if not identity_provider or not identity_provider.is_active:
        raise RuntimeError("Google OAuth identity provider is unavailable")
    config = await _discover_provider_configuration(identity_provider)
    token_endpoint = str(identity_provider.token_endpoint or config.get("token_endpoint") or "").strip()
    if not token_endpoint:
        raise RuntimeError("Google OAuth token endpoint is unavailable")
    client_secret = await _provider_client_secret(db, identity_provider)
    refresh_tool_name, refresh_field_name = provider_secret_scope(provider, "refresh_token")
    refresh_token = await get_secret_value_func(
        db,
        tool_name=refresh_tool_name,
        field_name=refresh_field_name,
        project_id=None,
    )
    if not refresh_token:
        raise RuntimeError("Google provider is not connected")
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": identity_provider.client_id,
                "client_secret": client_secret or "",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Google OAuth refresh did not return an access token")
    return access_token, project_id
