"""Standalone GitHub Copilot OAuth helpers for Octryx."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import LLMProvider
from ...time_utils import utc_now_aware
from ..control_plane.provider_auth import provider_secret_scope
from ..provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata

COPILOT_OAUTH_CLIENT_ID = ""


def get_copilot_oauth_client_id() -> str:
    return str(get_settings().copilot_oauth_client_id or COPILOT_OAUTH_CLIENT_ID or "").strip()


def require_copilot_oauth_client_id() -> str:
    client_id = get_copilot_oauth_client_id()
    if not client_id:
        raise ValueError(
            "COPILOT_OAUTH_CLIENT_ID must be configured with an Octryx-owned GitHub OAuth app "
            "before starting Copilot device login."
        )
    return client_id


async def begin_copilot_device_flow() -> dict[str, Any]:
    client_id = require_copilot_oauth_client_id()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://github.com/login/device/code",
            json={
                "client_id": client_id,
                "scope": "read:user",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "octryx/0.0.1-alpha",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload.setdefault("client_id", client_id)
        return payload


async def poll_copilot_device_flow(device_code: str) -> dict[str, Any]:
    client_id = require_copilot_oauth_client_id()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "octryx/0.0.1-alpha",
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_copilot_access_token(refresh_token: str) -> dict[str, Any]:
    client_id = require_copilot_oauth_client_id()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "octryx/0.0.1-alpha",
            },
        )
        response.raise_for_status()
        return response.json()


async def fetch_github_user_profile(access_token: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "octryx/0.0.1-alpha",
            },
        )
        if response.status_code >= 400:
            return None
        return response.json()


def _expiry_from_now(now: datetime, expires_in: Any) -> str | None:
    return (now + timedelta(seconds=int(expires_in))).isoformat() if str(expires_in or "").strip() else None


def _token_metadata(token_data: dict[str, Any], profile: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    refresh_expires_in = token_data.get("refresh_token_expires_in")
    access_expires_in = token_data.get("expires_in")
    return {
        "login": str((profile or {}).get("login") or "").strip(),
        "name": str((profile or {}).get("name") or "").strip(),
        "source": "github_device_flow",
        "host": "https://github.com",
        "token_type": str(token_data.get("token_type") or "bearer").strip() or "bearer",
        "access_token_expires_at": _expiry_from_now(now, access_expires_in),
        "refresh_token_expires_at": _expiry_from_now(now, refresh_expires_in),
    }


async def persist_copilot_oauth_tokens(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    token_data: dict[str, Any],
    set_secret_value_func: Callable[..., Any],
    fetch_profile_func: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    access_token = str(token_data.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Copilot OAuth token response did not include access_token")

    access_tool_name, access_field_name = provider_secret_scope(provider)
    access_secret_entry = await set_secret_value_func(
        db,
        tool_name=access_tool_name,
        field_name=access_field_name,
        project_id=None,
        value=access_token,
    )

    refresh_token = str(token_data.get("refresh_token") or "").strip()
    now = utc_now_aware()
    meta = await read_oauth_metadata(db, provider)

    if refresh_token:
        refresh_tool_name, refresh_field_name = provider_secret_scope(provider, "refresh_token")
        await set_secret_value_func(
            db,
            tool_name=refresh_tool_name,
            field_name=refresh_field_name,
            project_id=None,
            value=refresh_token,
        )
    profile_loader = fetch_profile_func or fetch_github_user_profile
    profile = await profile_loader(access_token)
    meta.update(_token_metadata(token_data, profile, now))
    provider.auth_mode = "oauth"
    provider.api_key_secret_ref = access_secret_entry.id
    await write_oauth_metadata(db, provider, meta)
    await db.commit()
    return {
        "login": meta.get("login", ""),
        "name": meta.get("name", ""),
        "access_token_expires_at": meta.get("access_token_expires_at"),
        "refresh_token_expires_at": meta.get("refresh_token_expires_at"),
    }


async def _load_access_token(
    db: AsyncSession, provider: LLMProvider, get_secret_value_func: Callable[..., Any]
) -> Any:
    # The provider's secret reference first, then the provider-scoped secret field.
    access_token = None
    if getattr(provider, "api_key_secret_ref", None):
        access_token = await get_secret_value_func(db, secret_id=provider.api_key_secret_ref)
    if not access_token:
        access_tool_name, access_field_name = provider_secret_scope(provider)
        access_token = await get_secret_value_func(
            db,
            tool_name=access_tool_name,
            field_name=access_field_name,
            project_id=None,
        )
    return access_token


def _access_token_needs_refresh(access_token: Any, expires_at: str) -> bool:
    needs_refresh = not access_token
    if access_token and expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            needs_refresh = expiry <= (utc_now_aware() + timedelta(minutes=5))
        except Exception:
            needs_refresh = False
    return needs_refresh


async def build_copilot_access_token(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    get_secret_value_func: Callable[..., Any],
    set_secret_value_func: Callable[..., Any],
) -> str:
    meta = await read_oauth_metadata(db, provider)
    access_token = await _load_access_token(db, provider, get_secret_value_func)

    expires_at = str(meta.get("access_token_expires_at") or "").strip()
    needs_refresh = _access_token_needs_refresh(access_token, expires_at)

    if not needs_refresh and access_token:
        return str(access_token)

    refresh_tool_name, refresh_field_name = provider_secret_scope(provider, "refresh_token")
    refresh_token = await get_secret_value_func(
        db,
        tool_name=refresh_tool_name,
        field_name=refresh_field_name,
        project_id=None,
    )
    if not refresh_token:
        if access_token:
            return str(access_token)
        raise ValueError("Copilot OAuth provider requires a stored access token or refresh token")

    token_data = await refresh_copilot_access_token(str(refresh_token))
    if str(token_data.get("error") or "").strip():
        raise ValueError(str(token_data.get("error_description") or token_data["error"]))
    persisted = await persist_copilot_oauth_tokens(
        db,
        provider=provider,
        token_data=token_data,
        set_secret_value_func=set_secret_value_func,
    )
    refreshed_access_token = await _load_access_token(db, provider, get_secret_value_func)
    if refreshed_access_token:
        return str(refreshed_access_token)
    login_or_provider = persisted.get("login") or provider.id
    raise ValueError(f"Copilot OAuth refresh succeeded but no access token could be loaded for {login_or_provider}")
