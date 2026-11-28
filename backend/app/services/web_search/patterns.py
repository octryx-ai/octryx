"""Source patterns of the trusted-source registry: what one entry means, and when a URL matches it."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_PATTERN_CHARS = 300
_HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

SHARED_HOSTS = frozenset(
    {
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "codeberg.org",
        "sourceforge.net",
        "raw.githubusercontent.com",
        "gist.github.com",
        "medium.com",
        "dev.to",
        "substack.com",
        "docs.google.com",
        "drive.google.com",
        "sites.google.com",
        "youtube.com",
        "linkedin.com",
        "reddit.com",
    }
)
HOSTING_SUFFIXES = frozenset(
    {
        "github.io",
        "gitlab.io",
        "readthedocs.io",
        "readthedocs.org",
        "netlify.app",
        "vercel.app",
        "pages.dev",
        "herokuapp.com",
        "blogspot.com",
        "wordpress.com",
        "azurewebsites.net",
        "cloudfront.net",
        "amazonaws.com",
        "web.app",
        "firebaseapp.com",
        "co.uk",
        "com.au",
        "co.jp",
        "com.br",
    }
)


class InvalidSourcePatternError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _host_of(value: str) -> str:
    host = value.strip().lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def normalize_pattern(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or len(text) > MAX_PATTERN_CHARS:
        raise InvalidSourcePatternError("empty_or_too_long")
    parts = urlsplit(text if "://" in text else f"https://{text}")
    if parts.scheme not in ("https", "http") or parts.username or parts.password or parts.port:
        raise InvalidSourcePatternError("not_a_host_pattern")
    host = _host_of(parts.hostname or "")
    if _is_address(host):
        raise InvalidSourcePatternError("address_not_allowed")
    if not _HOST.match(host):
        raise InvalidSourcePatternError("not_a_host_pattern")
    if host in HOSTING_SUFFIXES:
        raise InvalidSourcePatternError("hosting_suffix")
    path = "/".join(segment for segment in parts.path.split("/") if segment)
    if host in SHARED_HOSTS and not path:
        raise InvalidSourcePatternError("shared_host_needs_path")
    return f"{host}/{path}" if path else host


def pattern_matches(pattern: str, url: str) -> bool:
    parts = urlsplit(url)
    host = _host_of(parts.hostname or "")
    pattern_host, _, prefix = pattern.partition("/")
    if not host or not (host == pattern_host or host.endswith(f".{pattern_host}")):
        return False
    if not prefix:
        return True
    path = "/".join(segment for segment in parts.path.split("/") if segment)
    return path == prefix or path.startswith(f"{prefix}/")


def pattern_host(pattern: str) -> str:
    return pattern.partition("/")[0]


def suggested_pattern(url: str) -> str | None:
    parts = urlsplit(url)
    host = _host_of(parts.hostname or "")
    segments = [segment for segment in parts.path.split("/") if segment]
    candidate = f"{host}/{'/'.join(segments[:2])}" if host in SHARED_HOSTS and segments else host
    try:
        return normalize_pattern(candidate)
    except InvalidSourcePatternError:
        return None


__all__ = [
    "HOSTING_SUFFIXES",
    "InvalidSourcePatternError",
    "SHARED_HOSTS",
    "normalize_pattern",
    "pattern_host",
    "pattern_matches",
    "suggested_pattern",
]
