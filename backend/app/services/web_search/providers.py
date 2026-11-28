"""Governed web search providers: real search APIs only, chosen by explicit configuration."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

PROVIDER_ENV = "OCTRYX_WEB_SEARCH_PROVIDER"
DATA_POLICY_CLASS_ENV = "OCTRYX_WEB_SEARCH_DATA_POLICY_CLASS"
# The data classification search queries may carry to the provider: a Workspace classified above it
# may not send queries out. Operators lower or raise it per Instance.
DEFAULT_DATA_POLICY_CLASS = "internal"
PROVIDERS = ("tavily", "exa")
MAX_RESULTS = 20
_KEY_ENV = {"tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY"}
_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


class SearchProviderError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published_date: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "published_date": self.published_date}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    api_key: str
    data_policy_class: str

    def __repr__(self) -> str:  # never render the key
        return f"ProviderConfig(name={self.name!r}, data_policy_class={self.data_policy_class!r})"


def provider_config(
    project_config: Mapping[str, Any] | None = None, environ: Mapping[str, str] | None = None
) -> ProviderConfig | None:
    source = os.environ if environ is None else environ
    keys = {
        "tavily": str(source.get(_KEY_ENV["tavily"]) or "").strip(),
        "exa": str((project_config or {}).get("exa_api_key") or source.get(_KEY_ENV["exa"]) or "").strip(),
    }
    named = str(source.get(PROVIDER_ENV) or "").strip().lower()
    if named:
        name = named if named in PROVIDERS and keys[named] else None
    else:
        name = next((candidate for candidate in PROVIDERS if keys[candidate]), None)
    if name is None:
        return None
    data_class = str(source.get(DATA_POLICY_CLASS_ENV) or DEFAULT_DATA_POLICY_CLASS).strip().lower()
    return ProviderConfig(name=name, api_key=keys[name], data_policy_class=data_class)


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _hits(items: object, *, snippet_key: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        snippet = item.get(snippet_key) or item.get("highlights") or ""
        if isinstance(snippet, list):
            snippet = " ".join(str(part) for part in snippet)
        hits.append(
            SearchHit(
                title=_clean(item.get("title"), 300) or url,
                url=url[:2048],
                snippet=_clean(snippet, 500),
                published_date=_clean(item.get("published_date") or item.get("publishedDate"), 40),
            )
        )
    return hits


# A connection that fails, or a provider that answers 429 / 5xx, is asked again after these pauses:
# transport failures are often intermittent (12 of 16 searches of one phase have failed ``transport``).
RETRY_DELAYS = (1.0, 3.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def _post(client_factory: Callable[..., Any], url: str, *, headers: dict, payload: dict) -> Any:
    response = None
    for delay in (*RETRY_DELAYS, None):
        try:
            async with client_factory(timeout=_TIMEOUT) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError:
            response = None
        if (response is not None and response.status_code not in RETRY_STATUSES) or delay is None:
            break
        await _sleep(delay)
    if response is None:
        raise SearchProviderError("transport")
    if response.status_code in (401, 403):
        raise SearchProviderError("unauthorized")
    if response.status_code == 429:
        raise SearchProviderError("rate_limited")
    if response.status_code != 200:
        raise SearchProviderError("status")
    try:
        return response.json()
    except ValueError:
        raise SearchProviderError("invalid_response") from None


async def search_provider(
    config: ProviderConfig,
    *,
    query: str,
    num_results: int,
    include_domains: list[str],
    exclude_domains: list[str],
    code: bool = False,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> list[SearchHit]:
    count = max(1, min(num_results, MAX_RESULTS))
    if config.name == "tavily":
        payload: dict[str, Any] = {"query": query, "max_results": count, "search_depth": "basic"}
        if include_domains:
            payload["include_domains"] = include_domains[:300]
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains[:150]
        data = await _post(
            client_factory,
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            payload=payload,
        )
        return _hits((data or {}).get("results") if isinstance(data, dict) else None, snippet_key="content")
    payload = {"query": query, "numResults": count, "type": "auto", "contents": {"text": {"maxCharacters": 500}}}
    if code:
        payload["category"] = "github"
    if include_domains:
        payload["includeDomains"] = include_domains[:100]
    if exclude_domains:
        payload["excludeDomains"] = exclude_domains[:100]
    data = await _post(
        client_factory,
        "https://api.exa.ai/search",
        headers={"x-api-key": config.api_key, "Content-Type": "application/json"},
        payload=payload,
    )
    return _hits((data or {}).get("results") if isinstance(data, dict) else None, snippet_key="text")


__all__ = [
    "DATA_POLICY_CLASS_ENV",
    "PROVIDERS",
    "PROVIDER_ENV",
    "ProviderConfig",
    "SearchHit",
    "SearchProviderError",
    "provider_config",
    "search_provider",
]
