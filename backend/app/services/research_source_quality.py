"""Research source quality: citation-grade titles, author/year metadata and source credibility checks."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .workflow_contracts.topic import topic_terms


def _normalize_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    hostname = (urlsplit(candidate).hostname or "").strip().lower().strip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


_TECHNICAL_SOURCE_MARKERS = frozenset(
    {"api", "integration", "integrations", "developer", "documentation", "rest", "webhook", "sdk"}
)
_TECHNICAL_AUTHORITY_HOST_PREFIXES = ("developer.", "developers.", "docs.", "support.", "help.", "api.")
_TECHNICAL_AUTHORITY_HOST_LABELS = frozenset(
    {"developer", "developers", "docs", "documentation", "support", "help", "api"}
)
_LOW_CREDIBILITY_AUTHORITY_HOST_PREFIXES = ("community.", "forum.", "forums.")
_TECHNICAL_AUTHORITY_URL_MARKERS = (
    "/docs/",
    "/documentation/",
    "/developer/",
    "/developers/",
    "/reference/",
    "/api/",
    "/rest-api",
    "/openapi",
    "/sdk/",
    "/support/",
    "/help/",
    "/hc/",
    "/knowledge-base/",
    "/kb/",
)
_TECHNICAL_AUTHORITY_TITLE_MARKERS = (
    "developer documentation",
    "developer docs",
    "api documentation",
    "api reference",
    "rest api reference",
    "rest api documentation",
    "developer guide",
    "integration guide",
    "openapi",
    "support article",
    "support documentation",
    "help center",
    "knowledge base",
)
_LOW_CREDIBILITY_TECHNICAL_PATH_MARKERS = (
    "/blog/",
    "/blogs/",
    "/insights/",
    "/post/",
    "/posts/",
    "/news/",
    "/articles/",
)
_LOW_CREDIBILITY_TECHNICAL_TITLE_PATTERNS = (
    re.compile(r"\ball you need to know\b", re.IGNORECASE),
    re.compile(r"\bultimate guide\b", re.IGNORECASE),
    re.compile(r"\bbest practices\b", re.IGNORECASE),
    re.compile(r"\btop solutions?\b", re.IGNORECASE),
    re.compile(r"\bdecoding\b", re.IGNORECASE),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$", re.IGNORECASE),
    re.compile(r"^published\s+[a-z]+\s+\d{1,2},\s+\d{4}$", re.IGNORECASE),
    re.compile(r"^table of contents:?$", re.IGNORECASE),
)
_MALFORMED_CITATION_TITLE_PATTERNS = (
    re.compile(r"^https?://", re.IGNORECASE),
    re.compile(r"^www\.", re.IGNORECASE),
    re.compile(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:[/#?].*)?$", re.IGNORECASE),
    re.compile(r"^\[[^]]+\]\([^)]*\)$", re.IGNORECASE),
    re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", re.IGNORECASE),
    re.compile(r"^\d{4}-\d{2}-\d{2}$", re.IGNORECASE),
    re.compile(r"^[a-z]+\s+\d{1,2},\s+\d{4}$", re.IGNORECASE),
    re.compile(r"^published\s+[a-z]+\s+\d{1,2},\s+\d{4}$", re.IGNORECASE),
    re.compile(r"^table of contents:?$", re.IGNORECASE),
    re.compile(r"^\d{3}\s+(bad request|not found|forbidden|unauthorized)\b", re.IGNORECASE),
    re.compile(r"this page has been loading for longer than expected", re.IGNORECASE),
)
_AUTHORITATIVE_DOCUMENT_URL_MARKERS = (
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    "/pdf/",
    "/pdfs/",
    "/whitepaper",
    "/white-paper",
    "/solution-brief",
    "/reference-architecture",
)
_AUTHORITATIVE_DOCUMENT_TEXT_MARKERS = (
    "pdf",
    "whitepaper",
    "white paper",
    "solution brief",
    "implementation guide",
    "reference architecture",
    "developer guide",
    "api guide",
)


def topic_requires_technical_sources(topic: str) -> bool:
    return bool(topic_terms(topic) & _TECHNICAL_SOURCE_MARKERS)


def research_source_title_is_citation_quality(title: str) -> bool:
    normalized_title = re.sub(r"\s+", " ", str(title or "").strip())
    if len(normalized_title) < 3 or len(normalized_title) > 240:
        return False
    return not any(pattern.search(normalized_title) for pattern in _MALFORMED_CITATION_TITLE_PATTERNS)


def research_source_has_authority_markers(*, title: str, url: str, snippet: str = "") -> bool:
    normalized_url = str(url or "").strip().lower()
    hostname = _normalize_domain(url)
    blob = " ".join(part for part in (title, snippet) if str(part or "").strip()).lower()
    if hostname.startswith(_LOW_CREDIBILITY_AUTHORITY_HOST_PREFIXES):
        return False
    if hostname.startswith(_TECHNICAL_AUTHORITY_HOST_PREFIXES):
        return True
    if _TECHNICAL_AUTHORITY_HOST_LABELS.intersection(hostname.split(".")):
        return True
    if any(marker in normalized_url for marker in _TECHNICAL_AUTHORITY_URL_MARKERS):
        return True
    return any(marker in blob for marker in _TECHNICAL_AUTHORITY_TITLE_MARKERS)


def research_source_has_authoritative_document_markers(*, title: str, url: str, snippet: str = "") -> bool:
    normalized_url = str(url or "").strip().lower()
    hostname = _normalize_domain(url)
    blob = " ".join(part for part in (title, snippet, url) if str(part or "").strip()).lower()
    if hostname.startswith(_LOW_CREDIBILITY_AUTHORITY_HOST_PREFIXES):
        return False
    if not any(marker in normalized_url for marker in _AUTHORITATIVE_DOCUMENT_URL_MARKERS):
        return False
    if not any(marker in blob for marker in (*_TECHNICAL_SOURCE_MARKERS, *_AUTHORITATIVE_DOCUMENT_TEXT_MARKERS)):
        return False
    if _TECHNICAL_AUTHORITY_HOST_LABELS.intersection(hostname.split(".")):
        return True
    return any(marker in normalized_url for marker in ("/solution-brief", "/whitepaper", "/reference-architecture"))


def research_source_is_credible(*, topic: str, title: str, url: str, snippet: str = "") -> bool:
    normalized_title = str(title or "").strip()
    normalized_url = str(url or "").strip().lower()
    if not normalized_url or not research_source_title_is_citation_quality(normalized_title):
        return False
    if not topic_requires_technical_sources(topic):
        return True

    low_credibility_path = any(marker in normalized_url for marker in _LOW_CREDIBILITY_TECHNICAL_PATH_MARKERS)
    low_credibility_title = any(
        pattern.search(normalized_title) for pattern in _LOW_CREDIBILITY_TECHNICAL_TITLE_PATTERNS
    )
    if low_credibility_path or low_credibility_title:
        return False
    has_authority_markers = research_source_has_authority_markers(title=title, url=url, snippet=snippet)
    has_authoritative_document_markers = research_source_has_authoritative_document_markers(
        title=title,
        url=url,
        snippet=snippet,
    )
    if not has_authority_markers and not has_authoritative_document_markers:
        return False
    return True


def research_url_is_credible(*, topic: str, url: str) -> bool:
    normalized_url = str(url or "").strip().lower()
    if not normalized_url:
        return False
    if not topic_requires_technical_sources(topic):
        return True
    if any(marker in normalized_url for marker in _LOW_CREDIBILITY_TECHNICAL_PATH_MARKERS):
        return False
    return research_source_has_authority_markers(
        title="", url=url, snippet=""
    ) or research_source_has_authoritative_document_markers(title="", url=url, snippet="")
