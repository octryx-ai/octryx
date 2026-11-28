"""The one governed web search of the platform (search control plane)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Session
from ..data_classification.effect_rules import REASON_WEB_SEARCH_OFF, web_search_off
from ..model_gateway.data_policy.gate import data_policy_decision
from ..model_gateway.data_policy.source import resolve_workspace_data_classification
from .health import host_within, quarantine, quarantine_reason
from .providers import SearchHit, SearchProviderError, provider_config, search_provider
from .registry import URL_BLOCKED, URL_TRUSTED, SourcePolicy, load_policy

MAX_QUERY_CHARS = 400
MAX_EXCLUDED_HOSTS = 150

STATE_OK = "ok"
STATE_INVALID_REQUEST = "invalid_request"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_DENIED = "denied"
STATE_UNAVAILABLE = "unavailable"

WEB_SEARCH_POLICY_KEY = "web_search_policy"
MODE_OPEN = "open"
MODE_TRUSTED_ONLY = "trusted_only"


@dataclass(slots=True)
class SearchOutcome:
    state: str
    reason: str
    provider: str | None = None
    hits: list[SearchHit] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    restricted_to: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state == STATE_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "provider": self.provider,
            "results": [hit.to_dict() for hit in self.hits],
            "count": len(self.hits),
            "dropped": dict(self.dropped),
            "restricted_to": list(self.restricted_to),
        }


def search_mode_of(config: object) -> str:
    section = config.get(WEB_SEARCH_POLICY_KEY) if isinstance(config, dict) else None
    mode = section.get("mode") if isinstance(section, dict) else None
    return MODE_TRUSTED_ONLY if mode == MODE_TRUSTED_ONLY else MODE_OPEN


async def stored_project_config(db: AsyncSession, project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return {}
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return dict(config) if isinstance(config, dict) else {}


async def workspace_search_mode(db: AsyncSession, project_id: str | None) -> str:
    return search_mode_of(await stored_project_config(db, project_id))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


async def _admitted(
    db: AsyncSession, project_id: str | None, session_id: str | None, data_policy_class: str
) -> SearchOutcome | None:
    metadata: dict[str, Any] | None = None
    if session_id:
        row = (await db.execute(select(Session.metadata_).where(Session.id == session_id))).scalar_one_or_none()
        metadata = dict(row or {})
    classification = await resolve_workspace_data_classification(db, project_id=project_id, session_metadata=metadata)
    if classification.resolved and web_search_off(classification.classification):
        # An added classification rule: web search is off at this level.
        return SearchOutcome(STATE_DENIED, REASON_WEB_SEARCH_OFF)
    decision = data_policy_decision(classification, data_policy_class)
    if decision.allowed:
        return None
    state = STATE_DENIED if classification.resolved else STATE_NEEDS_CONFIGURATION
    return SearchOutcome(state, decision.reason)


def _restriction(
    policy: SourcePolicy, *, trusted_only: bool, product: str | None, restrict_to: list[str]
) -> list[str] | None:
    if not trusted_only:
        return restrict_to
    trusted = policy.trusted_hosts(product)
    if not restrict_to:
        return trusted or None
    narrowed = [host for host in restrict_to if host_within(host, trusted)]
    return narrowed or None


async def governed_search(
    db: AsyncSession,
    *,
    project_id: str | None,
    query: str,
    num_results: int = 8,
    trusted_only: bool,
    product: str | None = None,
    restrict_to: list[str] | None = None,
    exclude: list[str] | None = None,
    code: bool = False,
    session_id: str | None = None,
    policy: SourcePolicy | None = None,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> SearchOutcome:
    text = " ".join(str(query or "").split())
    if not text or len(text) > MAX_QUERY_CHARS:
        return SearchOutcome(STATE_INVALID_REQUEST, "query_empty_or_too_long")
    config = provider_config(await stored_project_config(db, project_id))
    if config is None:
        return SearchOutcome(STATE_NEEDS_CONFIGURATION, "provider_not_configured")
    held = quarantine_reason(config.name)
    if held:
        return SearchOutcome(STATE_UNAVAILABLE, held, provider=config.name)
    refusal = await _admitted(db, project_id, session_id, config.data_policy_class)
    if refusal is not None:
        refusal.provider = config.name
        return refusal
    policy = policy or await load_policy(db, project_id=project_id)
    include = _restriction(policy, trusted_only=trusted_only, product=product, restrict_to=list(restrict_to or []))
    if include is None:
        return SearchOutcome(STATE_NEEDS_CONFIGURATION, "no_trusted_sources", provider=config.name)
    excluded = sorted({*policy.blocked_hosts(), *(exclude or [])})[:MAX_EXCLUDED_HOSTS]
    try:
        hits = await search_provider(
            config,
            query=text,
            num_results=num_results,
            include_domains=include,
            exclude_domains=excluded,
            code=code,
            client_factory=client_factory,
        )
    except SearchProviderError as error:
        return SearchOutcome(STATE_UNAVAILABLE, error.reason, provider=config.name)
    if include and any(not host_within(_host(hit.url), include) for hit in hits):
        quarantine(config.name, "answer_off_restriction")
        return SearchOutcome(STATE_UNAVAILABLE, "answer_off_restriction", provider=config.name)
    kept: list[SearchHit] = []
    dropped = {"blocked": 0, "outside_trusted": 0, "excluded": 0}
    for hit in hits:
        state = policy.state_of(hit.url, product)
        if state == URL_BLOCKED:
            dropped["blocked"] += 1
        elif trusted_only and state != URL_TRUSTED:
            dropped["outside_trusted"] += 1
        elif excluded and host_within(_host(hit.url), excluded):
            dropped["excluded"] += 1
        else:
            kept.append(hit)
    return SearchOutcome(STATE_OK, "ok", provider=config.name, hits=kept, dropped=dropped, restricted_to=list(include))


__all__ = [
    "MODE_OPEN",
    "MODE_TRUSTED_ONLY",
    "STATE_DENIED",
    "STATE_INVALID_REQUEST",
    "STATE_NEEDS_CONFIGURATION",
    "STATE_OK",
    "STATE_UNAVAILABLE",
    "SearchOutcome",
    "WEB_SEARCH_POLICY_KEY",
    "governed_search",
    "search_mode_of",
    "stored_project_config",
    "workspace_search_mode",
]
