"""Find candidate sources the way a researcher does, grounded in pages that exist. Web search is never open here; every
candidate was observed on the web."""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

from ...web_search.registry import URL_BLOCKED, SourcePolicy
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.source_url import normalize_source_url
from ..sources.web_fetch import FetchRefusedError, fetch_public_document, probe_public_document

MAX_SEEDS = 10
MAX_CANDIDATES = 80
MAX_LINKS_PER_SEED = 400
_CONCURRENCY = 4
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_LINK = re.compile(r"<a\s[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Candidate:
    url: str
    title: str
    snippet: str


def _text(raw: str, limit: int) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", raw)).split())[:limit]


def _safe_url(raw: str, base: str | None = None) -> str | None:
    url = urldefrag(urljoin(base, raw) if base else raw)[0].strip()
    try:
        url = normalize_source_url(url) or ""
    except InvalidEvidenceRequestError:
        return None
    return url if url.startswith("https://") else None


def product_terms(product: str, versions: list[str]) -> list[str]:
    words = product.replace("-", " ")
    return [term.lower() for term in {product, words, words.replace(" ", ""), *versions} if term]


def _version_score(text: str, versions: list[str]) -> int:
    lowered = text.lower()
    return sum(2 for version in versions if version and (version in lowered or version.replace(".", "-") in lowered))


def _mentions(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


EntryPoint = tuple[str, str, list[tuple[str, str]]]


async def _seed_page(url: str, gate: asyncio.Semaphore, policy: SourcePolicy) -> EntryPoint | None:
    async with gate:
        try:
            document = await fetch_public_document(url)
        except FetchRefusedError:
            return None
    if policy.state_of(document.url) == URL_BLOCKED:
        return None
    if document.media_type != "text/html":
        return document.url, url, []
    page = document.data.decode("utf-8", errors="replace")
    title_match = _TITLE.search(page)
    links = [(href, _text(text, 160)) for href, text in _LINK.findall(page)[:MAX_LINKS_PER_SEED]]
    return document.url, _text(title_match.group(1), 200) if title_match else url, links


async def entry_points(seeds: list[str], policy: SourcePolicy) -> list[EntryPoint]:
    gate = asyncio.Semaphore(_CONCURRENCY)
    seed_urls = [
        url for url in (_safe_url(raw) for raw in seeds[:MAX_SEEDS]) if url and policy.state_of(url) != URL_BLOCKED
    ]
    return [page for page in await asyncio.gather(*(_seed_page(url, gate, policy) for url in seed_urls)) if page]


def entry_point_hosts(pages: list[EntryPoint]) -> list[str]:
    return sorted({(urlsplit(final_url).hostname or "").removeprefix("www.") for final_url, _, _ in pages} - {""})


def discover(
    *, pages: list[EntryPoint], search: list[Candidate], product: str, versions: list[str], policy: SourcePolicy
) -> tuple[list[Candidate], dict[str, int]]:
    terms = product_terms(product, versions)
    candidates: dict[str, Candidate] = {}

    def add(url: str | None, title: str, snippet: str = "") -> None:
        if url and url not in candidates and len(candidates) < MAX_CANDIDATES and policy.state_of(url) != URL_BLOCKED:
            candidates[url] = Candidate(url, title or url, snippet)

    for final_url, title, _ in pages:
        add(_safe_url(final_url), title, "official entry point")
    # Ranked, because a project wiki links every page it has: a link naming one of the package's
    # versions comes before one that only names the product, and search results come last.
    ranked: list[tuple[int, int, str, str, str]] = []
    for final_url, _, links in pages:
        host = urlsplit(final_url).hostname
        for href, text in links:
            url = _safe_url(href, final_url)
            if url and urlsplit(url).hostname == host and _mentions(f"{url} {text}", terms):
                ranked.append(
                    (
                        _version_score(f"{url} {text}", versions),
                        len(ranked),
                        url,
                        text,
                        "linked from an official entry point",
                    )
                )
    for item in search:
        score = _version_score(f"{item.url} {item.title}", versions) - 1
        ranked.append((score, len(ranked), item.url, item.title, item.snippet))
    for _, _, url, title, snippet in sorted(ranked, key=lambda entry: (-entry[0], entry[1])):
        add(url, title, snippet)
    stats = {"seeds_fetched": len(pages), "search_results": len(search)}
    return list(candidates.values()), stats


async def verified(urls: list[str]) -> set[str]:
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def probe(url: str) -> str | None:
        async with gate:
            try:
                await probe_public_document(url)
                return url
            except FetchRefusedError:
                return None

    return {url for url in await asyncio.gather(*(probe(url) for url in urls)) if url}


__all__ = ["Candidate", "EntryPoint", "discover", "entry_point_hosts", "entry_points", "product_terms", "verified"]
