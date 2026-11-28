"""The one source check before any ``web_fetch``: chat, MCP and every other caller (C-MCP-3)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .blocklist import platform_blocklist
from .registry import URL_BLOCKED, URL_TRUSTED, load_policy
from .service import MODE_TRUSTED_ONLY, workspace_search_mode

MAX_URL_CHARS = 2048

SOURCE_BLOCKED = {"state": "denied", "reason": "source_blocked", "error": "This source is blocked for web access."}
SOURCE_NOT_TRUSTED = {
    "state": "denied",
    "reason": "source_not_trusted",
    "error": "This Workspace fetches only from trusted sources, and this URL is not one.",
}
INVALID_URL = {"state": "invalid_request", "reason": "invalid_url", "error": "url must be an absolute http(s) URL."}


def normalized_fetch_url(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > MAX_URL_CHARS or not url.lower().startswith(("http://", "https://")):
        return None
    return url


async def web_fetch_refusal(
    db: AsyncSession | None, *, project_id: str | None, url: object
) -> dict[str, Any] | None:
    normalized = normalized_fetch_url(url)
    if normalized is None:
        return dict(INVALID_URL)
    if db is None:
        # No database (a tool run outside any Workspace): only the code-owned platform blocklist applies.
        return dict(SOURCE_BLOCKED) if platform_blocklist().category_of(normalized) else None
    policy = await load_policy(db, project_id=project_id)
    state = policy.state_of(normalized)
    if state == URL_BLOCKED:
        return dict(SOURCE_BLOCKED)
    if project_id and await workspace_search_mode(db, project_id) == MODE_TRUSTED_ONLY and state != URL_TRUSTED:
        return dict(SOURCE_NOT_TRUSTED)
    return None


__all__ = ["INVALID_URL", "SOURCE_BLOCKED", "SOURCE_NOT_TRUSTED", "normalized_fetch_url", "web_fetch_refusal"]
