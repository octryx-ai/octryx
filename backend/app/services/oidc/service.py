"""OIDC sign-in flow: the authorization redirect, the callback that signs the user in, and token refresh."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...http_security import set_auth_cookies
from ...models import IdentityProvider, OAuthSession
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..auth import create_access_token, create_refresh_token, rotate_refresh_token
from ..oidc_claims import merge_oidc_claims, resolve_identity_claims
from ..oidc_provider_config import build_authorization_url, resolve_provider_endpoints
from .id_token import _decode_id_token_claims
from .provider_http import (
    _discover_provider_configuration,
    _exchange_authorization_code,
    _fetch_userinfo_claims,
    _provider_client_secret,
)
from .providers import DEFAULT_SCOPE
from .provisioning import _apply_access_mappings, _find_or_provision_user, _record_identity_login

ProviderDiscover = Callable[[IdentityProvider], Awaitable[dict[str, Any]]]
AuthorizationCodeExchange = Callable[..., Awaitable[dict[str, Any]]]
UserinfoFetcher = Callable[[str, str], Awaitable[dict[str, Any]]]
ProviderSecretLookup = Callable[[AsyncSession, IdentityProvider], Awaitable[str | None]]
IdTokenClaimsDecoder = Callable[..., Awaitable[dict[str, Any]]]


def _base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _oauth_cookie_redirect(
    response,
    access_token: str,
    refresh_token: str | None,
    *,
    request: Request | None = None,
) -> None:
    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        request=request,
    )


def _normalize_target_path(target_path: str | None) -> str:
    candidate = str(target_path or "/chat").strip() or "/chat"
    if not candidate.startswith("/"):
        return "/chat"
    return candidate


async def build_oidc_authorization_redirect(
    db: AsyncSession,
    *,
    provider_id: str,
    redirect_uri: str,
    target_path: str,
    requested_by_user_id: str | None = None,
    discover_provider_configuration: ProviderDiscover | None = None,
) -> str:
    # Resolve at call time so monkeypatched module attributes take effect.
    discover_provider_configuration = discover_provider_configuration or _discover_provider_configuration
    stmt = select(IdentityProvider).where(IdentityProvider.id == provider_id)
    provider = (await db.execute(stmt)).scalar_one_or_none()
    if not provider or not provider.is_active:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    config = await discover_provider_configuration(provider)
    endpoints = resolve_provider_endpoints(provider, config, require_authorization=True)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _base64url_sha256(code_verifier)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session = OAuthSession(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        state=state,
        code_verifier=code_verifier,
        nonce=nonce,
        redirect_path=_normalize_target_path(target_path),
        requested_by_user_id=requested_by_user_id,
        expires_at=utc_now() + timedelta(minutes=10),
    )
    db.add(session)
    await db.commit()

    return build_authorization_url(
        authorization_endpoint=endpoints.authorization_endpoint,
        client_id=str(provider.client_id or "").strip(),
        redirect_uri=redirect_uri,
        scopes=list(provider.scopes_json or DEFAULT_SCOPE),
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )


async def _consumable_oauth_session(db: AsyncSession, state: str) -> OAuthSession:
    oauth_session = (await db.execute(select(OAuthSession).where(OAuthSession.state == state))).scalar_one_or_none()
    if not oauth_session:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if oauth_session.consumed_at:
        raise HTTPException(status_code=400, detail="OAuth session already consumed")
    if ensure_utc(oauth_session.expires_at) <= utc_now_aware():
        raise HTTPException(status_code=400, detail="OAuth session expired")
    return oauth_session


async def _provider_claims(
    db: AsyncSession,
    *,
    provider: IdentityProvider,
    oauth_session: OAuthSession,
    code: str,
    redirect_uri: str,
    discover_provider_configuration: ProviderDiscover,
    exchange_authorization_code: AuthorizationCodeExchange,
    fetch_userinfo_claims: UserinfoFetcher,
    provider_client_secret: ProviderSecretLookup,
    decode_id_token_claims: IdTokenClaimsDecoder,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    config = await discover_provider_configuration(provider)
    endpoints = resolve_provider_endpoints(provider, config, require_token_userinfo=True)

    client_secret = await provider_client_secret(db, provider)
    token_response = await exchange_authorization_code(
        provider=provider,
        token_endpoint=endpoints.token_endpoint,
        client_secret=client_secret,
        code=code,
        code_verifier=oauth_session.code_verifier,
        redirect_uri=redirect_uri,
    )
    access_token = str(token_response.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="Identity provider did not return an access token")
    raw_id_token = str(token_response.get("id_token") or "").strip()
    id_token_claims = await decode_id_token_claims(
        provider=provider,
        config=config,
        id_token=raw_id_token,
        nonce=oauth_session.nonce,
    )
    userinfo_claims = await fetch_userinfo_claims(endpoints.userinfo_endpoint, access_token)
    claims = merge_oidc_claims(userinfo_claims, id_token_claims)
    return token_response, access_token, raw_id_token, claims


async def complete_oidc_callback(
    db: AsyncSession,
    *,
    state: str,
    code: str,
    redirect_uri: str,
    discover_provider_configuration: ProviderDiscover | None = None,
    exchange_authorization_code: AuthorizationCodeExchange | None = None,
    fetch_userinfo_claims: UserinfoFetcher | None = None,
    provider_client_secret: ProviderSecretLookup | None = None,
    decode_id_token_claims: IdTokenClaimsDecoder | None = None,
) -> dict[str, Any]:
    oauth_session = await _consumable_oauth_session(db, state)
    provider = await db.get(IdentityProvider, oauth_session.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    # Resolve at call time so monkeypatched module attributes take effect.
    token_response, access_token, raw_id_token, claims = await _provider_claims(
        db,
        provider=provider,
        oauth_session=oauth_session,
        code=code,
        redirect_uri=redirect_uri,
        discover_provider_configuration=discover_provider_configuration or _discover_provider_configuration,
        exchange_authorization_code=exchange_authorization_code or _exchange_authorization_code,
        fetch_userinfo_claims=fetch_userinfo_claims or _fetch_userinfo_claims,
        provider_client_secret=provider_client_secret or _provider_client_secret,
        decode_id_token_claims=decode_id_token_claims or _decode_id_token_claims,
    )
    resolved_claims = resolve_identity_claims(provider, claims)
    user, identity = await _find_or_provision_user(db, provider=provider, resolved_claims=resolved_claims)
    _record_identity_login(
        identity=identity, user=user, resolved_claims=resolved_claims, claims=claims, access_token=access_token,
        raw_id_token=raw_id_token,
    )
    assigned_roles, assigned_groups = await _apply_access_mappings(
        db, user=user, provider=provider, external_groups=resolved_claims.external_groups
    )
    oauth_session.consumed_at = utc_now()
    app_refresh_token = await create_refresh_token(
        db,
        user_id=user.id,
        provider_id=provider.id,
        user_identity_id=identity.id,
        external_refresh_token=str(token_response.get("refresh_token") or "").strip() or None,
    )
    await db.commit()

    return {
        "user": user,
        "identity": identity,
        "access_token": create_access_token(user.id),
        "refresh_token": app_refresh_token,
        "redirect_path": _normalize_target_path(oauth_session.redirect_path),
        "assigned_roles": assigned_roles,
        "assigned_groups": assigned_groups,
        "provider": provider,
    }


async def refresh_access_token(
    db: AsyncSession,
    *,
    refresh_token: str,
) -> dict[str, Any]:
    user, rotated_refresh_token, _token_row = await rotate_refresh_token(db, refresh_token)
    return {
        "user": user,
        "access_token": create_access_token(user.id),
        "refresh_token": rotated_refresh_token,
    }


__all__ = [
    "_base64url_sha256",
    "_normalize_target_path",
    "_oauth_cookie_redirect",
    "build_oidc_authorization_redirect",
    "complete_oidc_callback",
    "refresh_access_token",
]
