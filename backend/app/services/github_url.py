"""GitHub URL normalization helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

PUBLIC_GITHUB_WEB_HOSTS = {"github.com", "www.github.com"}
PUBLIC_GITHUB_API_URL = "https://api.github.com"


def normalize_github_api_base_url(value: Any) -> str:
    """Return a GitHub REST API base URL from user-entered connector config."""

    raw_url = str(value or "").strip().rstrip("/") or PUBLIC_GITHUB_API_URL
    parsed = urlparse(raw_url)
    host = (parsed.netloc or parsed.path).split("/", 1)[0].lower()
    path = parsed.path.rstrip("/")
    if host in PUBLIC_GITHUB_WEB_HOSTS:
        return PUBLIC_GITHUB_API_URL
    if host == "api.github.com":
        return PUBLIC_GITHUB_API_URL
    if path.endswith("/api/v3"):
        return raw_url
    return raw_url


PUBLIC_GITHUB_WEB_URL = "https://github.com"


def github_web_base_url(api_base_url: Any) -> str | None:
    """The web base of a GitHub REST API base: ``github.com`` for the public API, the Enterprise host
    for ``https://host/api/v3``; ``None`` for any other form, so no web link is ever guessed."""

    api_base = normalize_github_api_base_url(api_base_url)
    if api_base == PUBLIC_GITHUB_API_URL:
        return PUBLIC_GITHUB_WEB_URL
    parsed = urlparse(api_base)
    path = parsed.path.rstrip("/")
    if parsed.scheme in {"http", "https"} and parsed.netloc and path.endswith("/api/v3"):
        return f"{parsed.scheme}://{parsed.netloc}{path[: -len('/api/v3')]}"
    return None
