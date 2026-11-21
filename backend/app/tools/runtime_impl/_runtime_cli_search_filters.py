"""Search query and result filtering helpers for runtime CLI tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

PREPRINT_DOMAIN_TOKENS = (
    "arxiv.org",
    "ssrn.com",
    "researchsquare.com",
    "biorxiv.org",
    "medrxiv.org",
)
PREPRINT_TEXT_TOKENS = (
    "preprint",
    "preview paper",
    "working paper",
    "research square",
    "arxiv",
    "ssrn",
)


def normalize_domain_token(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    hostname = (urlsplit(candidate).hostname or "").strip().lower().strip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def result_hostname(url: str) -> str:
    return normalize_domain_token(url)


def matches_domain_filter(hostname: str, domains: list[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def search_result_allowed(
    result: dict[str, Any],
    *,
    include_domains: list[str],
    exclude_domains: list[str],
    exclude_terms: list[str],
    exclude_preprints: bool,
) -> bool:
    url = str(result.get("url") or "").strip()
    hostname = result_hostname(url)
    if include_domains and (not hostname or not matches_domain_filter(hostname, include_domains)):
        return False
    if exclude_domains and hostname and matches_domain_filter(hostname, exclude_domains):
        return False
    blob = " ".join(
        [
            str(result.get("title") or ""),
            str(result.get("snippet") or ""),
            url,
        ]
    ).lower()
    if exclude_terms and any(term in blob for term in exclude_terms):
        return False
    if exclude_preprints and (
        any(token in hostname for token in PREPRINT_DOMAIN_TOKENS)
        or any(token in blob for token in PREPRINT_TEXT_TOKENS)
    ):
        return False
    return True


def apply_search_query_filters(
    query: str,
    *,
    include_domains: list[str],
    exclude_domains: list[str],
    exclude_terms: list[str],
    exclude_preprints: bool,
) -> str:
    parts = [str(query or "").strip()]
    if include_domains:
        parts.extend(f"site:{domain}" for domain in include_domains[:4])
    if exclude_domains:
        parts.extend(f"-site:{domain}" for domain in exclude_domains[:6])
    if exclude_preprints:
        parts.extend(["-site:arxiv.org", "-site:ssrn.com", "-preprint", '-"working paper"', '-"preview paper"'])
    for term in exclude_terms[:6]:
        normalized = str(term or "").strip()
        if not normalized:
            continue
        parts.append(f'-"{normalized}"' if " " in normalized else f"-{normalized}")
    return " ".join(part for part in parts if part)
