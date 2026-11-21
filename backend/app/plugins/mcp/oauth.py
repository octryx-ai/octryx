"""OAuth helpers for MCP HTTP transports."""

import logging
import time

import httpx

from app.services.error_facts import error_text

from .models import OAuthConfig

log = logging.getLogger(__name__)


async def _oauth_register_client(oauth: OAuthConfig, server_url: str) -> bool:
    """Perform Dynamic Client Registration (RFC 7591) if registration_url is set."""
    if not oauth.registration_url:
        return bool(oauth.client_id)

    payload = {
        "client_name": "Octryx MCP Client",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
        "grant_types": ["client_credentials", "refresh_token"],
        "scope": " ".join(oauth.scopes),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(oauth.registration_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            oauth.client_id = data.get("client_id", oauth.client_id)
            oauth.client_secret = data.get("client_secret", oauth.client_secret)
            log.info("Dynamic Client Registration succeeded: client_id=%s", oauth.client_id)
            return True
    except Exception as exc:
        log.warning("Dynamic Client Registration failed: %s", error_text("mcp_client_registration_failed", exc))
        return False


async def _oauth_fetch_token(oauth: OAuthConfig) -> bool:
    """Fetch or refresh an OAuth 2.0 access token."""
    if not oauth.token_url:
        return False

    if oauth.refresh_token:
        grant_data = {
            "grant_type": "refresh_token",
            "refresh_token": oauth.refresh_token,
            "client_id": oauth.client_id,
            "client_secret": oauth.client_secret,
        }
    else:
        grant_data = {
            "grant_type": "client_credentials",
            "client_id": oauth.client_id,
            "client_secret": oauth.client_secret,
            "scope": " ".join(oauth.scopes),
        }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                oauth.token_url,
                data=grant_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            oauth.access_token = data.get("access_token", "")
            if "refresh_token" in data:
                oauth.refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in") or 3600)
            oauth.token_expires_at = time.time() + expires_in - 60
            log.info("OAuth token fetched, expires in %ss", expires_in)
            return bool(oauth.access_token)
    except Exception as exc:
        log.warning("OAuth token fetch failed: %s", error_text("mcp_oauth_token_fetch_failed", exc))
        return False


async def _ensure_token(oauth: OAuthConfig) -> str | None:
    """Return a valid access token, refreshing if needed."""
    if not oauth.access_token or time.time() >= oauth.token_expires_at:
        ok = await _oauth_fetch_token(oauth)
        if not ok:
            return None
    return oauth.access_token


def _auth_headers(oauth: OAuthConfig | None) -> dict[str, str]:
    """Build auth headers for authenticated MCP HTTP requests."""
    if oauth and oauth.access_token:
        return {"Authorization": f"Bearer {oauth.access_token}"}
    return {}
