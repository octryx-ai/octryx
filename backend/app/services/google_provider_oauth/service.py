"""Google Gemini provider OAuth helpers for admin-managed provider credentials."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityProvider, LLMProvider, OAuthSession
from ...models.runtime.provider_oauth_config import oauth_metadata_from_provider
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..control_plane.provider_auth import provider_secret_scope
from ..oidc import (
    DEFAULT_SCOPE,
    _discover_provider_configuration,
    _exchange_authorization_code,
    _fetch_userinfo_claims,
    _normalize_target_path,
    _provider_client_secret,
)
from ..provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata
from ..secret import get_secret_value, set_secret_value

GOOGLE_GEMINI_SCOPE = "https://www.googleapis.com/auth/generative-language"
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def _provider_meta(provider: LLMProvider) -> dict[str, Any]:
    return oauth_metadata_from_provider(provider)


def _google_target_path(provider_id: str) -> str:
    return "/chat"


async def ensure_google_identity_provider(
    db: AsyncSession,
    *,
    provider: LLMProvider,
) -> IdentityProvider:
    meta = await read_oauth_metadata(db, provider)
    client_id = str(meta.get("oauth_client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="Google provider is missing OAuth client ID")
    client_secret_tool_name, client_secret_field_name = provider_secret_scope(
        provider,
        "google_oauth_client_secret",
    )
    client_secret = await get_secret_value(
        db,
        tool_name=client_secret_tool_name,
        field_name=client_secret_field_name,
        project_id=None,
    )
    client_secret = str(client_secret or "").strip()
    if not client_secret:
        raise HTTPException(status_code=400, detail="Google provider is missing OAuth client secret")

    identity_provider_id = str(meta.get("oauth_identity_provider_id") or "").strip()
    identity_provider = await db.get(IdentityProvider, identity_provider_id) if identity_provider_id else None
    if identity_provider is None:
        identity_provider = IdentityProvider(id=str(uuid.uuid4()))
        db.add(identity_provider)

    identity_provider.name = f"Google OAuth · {provider.display_name or provider.name}"
    identity_provider.provider_type = "google"
    identity_provider.issuer_url = GOOGLE_ISSUER
    identity_provider.discovery_url = GOOGLE_DISCOVERY_URL
    identity_provider.client_id = client_id
    identity_provider.scopes_json = [*DEFAULT_SCOPE, GOOGLE_GEMINI_SCOPE]
    identity_provider.auto_provision_users = False
    identity_provider.is_active = True

    secret_entry = await set_secret_value(
        db,
        tool_name=f"identity_provider:{identity_provider.id}",
        field_name="client_secret",
        project_id=None,
        value=client_secret,
    )
    identity_provider.client_secret_secret_ref = secret_entry.id

    meta["oauth_identity_provider_id"] = identity_provider.id
    await write_oauth_metadata(db, provider, meta)
    await db.flush()
    return identity_provider


async def build_google_provider_authorization_redirect(
    db: AsyncSession,
    *,
    llm_provider_id: str,
    redirect_uri: str,
    requested_by_user_id: str | None = None,
) -> str:
    provider = await db.get(LLMProvider, llm_provider_id)
    if not provider or provider.driver != "gemini_api":
        raise HTTPException(status_code=404, detail="Google provider not found")
    meta = await read_oauth_metadata(db, provider)
    project_id = str(meta.get("google_cloud_project") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="Google provider is missing Google Cloud project")
    identity_provider = await ensure_google_identity_provider(db, provider=provider)
    config = await _discover_provider_configuration(identity_provider)
    authorization_endpoint = str(
        identity_provider.authorization_endpoint or config.get("authorization_endpoint") or ""
    ).strip()
    if not authorization_endpoint:
        raise HTTPException(status_code=400, detail="Google OAuth discovery is missing authorization endpoint")

    from ..oidc import _base64url_sha256

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _base64url_sha256(code_verifier)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session = OAuthSession(
        id=str(uuid.uuid4()),
        provider_id=identity_provider.id,
        state=state,
        code_verifier=code_verifier,
        nonce=nonce,
        redirect_path=_google_target_path(provider.id),
        requested_by_user_id=requested_by_user_id,
        expires_at=utc_now() + timedelta(minutes=10),
    )
    db.add(session)
    await db.commit()

    params = {
        "response_type": "code",
        "client_id": identity_provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(identity_provider.scopes_json or [*DEFAULT_SCOPE, GOOGLE_GEMINI_SCOPE]),
        "state": state,
        "nonce": nonce,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


def _parse_provider_id_from_redirect_path(redirect_path: str) -> str:
    parsed = urlparse(_normalize_target_path(redirect_path))
    provider_id = (parse_qs(parsed.query).get("google_provider_id") or [""])[0].strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="OAuth session is missing target provider")
    return provider_id


async def _consumable_oauth_session(db: AsyncSession, state: str) -> OAuthSession:
    oauth_session = (await db.execute(select(OAuthSession).where(OAuthSession.state == state))).scalar_one_or_none()
    if not oauth_session:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if oauth_session.consumed_at:
        raise HTTPException(status_code=400, detail="OAuth session already consumed")
    if ensure_utc(oauth_session.expires_at) <= utc_now_aware():
        raise HTTPException(status_code=400, detail="OAuth session expired")
    return oauth_session


async def _callback_providers(db: AsyncSession, oauth_session: OAuthSession) -> tuple[IdentityProvider, LLMProvider]:
    identity_provider = await db.get(IdentityProvider, oauth_session.provider_id)
    if not identity_provider or not identity_provider.is_active:
        raise HTTPException(status_code=404, detail="Google identity provider not found")
    llm_provider_id = _parse_provider_id_from_redirect_path(oauth_session.redirect_path)
    provider = await db.get(LLMProvider, llm_provider_id)
    if not provider or provider.driver != "gemini_api":
        raise HTTPException(status_code=404, detail="Google provider not found")
    return identity_provider, provider


async def _store_google_connection(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    identity_provider: IdentityProvider,
    oauth_session: OAuthSession,
    refresh_token: str,
    email: str,
    name: str,
) -> None:
    refresh_tool_name, refresh_field_name = provider_secret_scope(provider, "refresh_token")
    secret_entry = await set_secret_value(
        db,
        tool_name=refresh_tool_name,
        field_name=refresh_field_name,
        project_id=None,
        value=refresh_token,
    )
    meta = await read_oauth_metadata(db, provider)
    meta.update(
        {
            "oauth_identity_provider_id": identity_provider.id,
            "login": email,
            "name": name,
            "host": GOOGLE_ISSUER,
            "source": "google_oauth",
        }
    )
    provider.auth_mode = "oauth"
    await write_oauth_metadata(db, provider, meta)
    provider.api_key_secret_ref = secret_entry.id
    oauth_session.consumed_at = utc_now()
    await db.commit()


async def complete_google_provider_oauth_callback(
    db: AsyncSession,
    *,
    state: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    oauth_session = await _consumable_oauth_session(db, state)
    identity_provider, provider = await _callback_providers(db, oauth_session)

    config = await _discover_provider_configuration(identity_provider)
    token_endpoint = str(identity_provider.token_endpoint or config.get("token_endpoint") or "").strip()
    userinfo_endpoint = str(identity_provider.userinfo_endpoint or config.get("userinfo_endpoint") or "").strip()
    if not token_endpoint or not userinfo_endpoint:
        raise HTTPException(status_code=400, detail="Google OAuth configuration is incomplete")

    client_secret = await _provider_client_secret(db, identity_provider)
    token_response = await _exchange_authorization_code(
        provider=identity_provider,
        token_endpoint=token_endpoint,
        client_secret=client_secret,
        code=code,
        code_verifier=oauth_session.code_verifier,
        redirect_uri=redirect_uri,
    )
    access_token = str(token_response.get("access_token") or "").strip()
    refresh_token = str(token_response.get("refresh_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="Google OAuth did not return an access token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Google OAuth did not return a refresh token")
    claims = await _fetch_userinfo_claims(userinfo_endpoint, access_token)
    email = str(claims.get("email") or "").strip()
    name = str(claims.get("name") or "").strip()

    await _store_google_connection(
        db,
        provider=provider,
        identity_provider=identity_provider,
        oauth_session=oauth_session,
        refresh_token=refresh_token,
        email=email,
        name=name,
    )
    return {
        "provider": provider,
        "redirect_path": _normalize_target_path(oauth_session.redirect_path),
        "login": email,
    }
