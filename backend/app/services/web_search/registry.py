"""The trusted-source registry: which sources web search and research may use (search control plane).

Admins own it. They add sources, trust or block what an agent proposed, and remove entries. An agent
may only *propose*: a research run that finds an official entry point outside the registry records it
as ``proposed`` with the page it verified, and nothing from it is ingested until an admin trusts it.

Precedence is closed and fail-safe. For one URL:

1. the platform blocklist (``blocklist.py``) blocks it;
2. a matching ``blocked`` entry, platform or Workspace, blocks it;
3. a matching ``trusted`` entry whose products are empty or include the product trusts it;
4. a matching ``proposed`` entry marks it as awaiting a decision;
5. otherwise it is unknown.

A Workspace sees the platform's entries and its own; a block always wins over a trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.project.web_trusted_sources import (
    ORIGIN_ADMIN,
    ORIGIN_AGENT,
    SCOPE_PLATFORM,
    SOURCE_STATE_BLOCKED,
    SOURCE_STATE_PROPOSED,
    SOURCE_STATE_TRUSTED,
    SOURCE_STATES,
    WebTrustedSource,
)
from ...time_utils import utc_now
from .blocklist import platform_blocklist
from .patterns import InvalidSourcePatternError, normalize_pattern, pattern_host, pattern_matches

MAX_PRODUCTS = 8
MAX_REASON_CHARS = 500
MAX_ENTRIES_PER_SCOPE = 500
_PRODUCT = re.compile(r"^[a-z0-9][a-z0-9.-]{0,59}$")

URL_BLOCKED = "blocked"
URL_TRUSTED = "trusted"
URL_PROPOSED = "proposed"


@dataclass(frozen=True, slots=True)
class SourceEntry:
    pattern: str
    products: tuple[str, ...]
    state: str
    scope: str

    def covers(self, product: str | None) -> bool:
        return not self.products or product is None or product in self.products


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    entries: tuple[SourceEntry, ...]

    def state_of(self, url: str, product: str | None = None) -> str | None:
        """``blocked``, ``trusted``, ``proposed`` or ``None`` for ``url`` (see the module docstring)."""
        if platform_blocklist().category_of(url):
            return URL_BLOCKED
        matching = [entry for entry in self.entries if pattern_matches(entry.pattern, url)]
        if any(entry.state == SOURCE_STATE_BLOCKED for entry in matching):
            return URL_BLOCKED
        if any(entry.state == SOURCE_STATE_TRUSTED and entry.covers(product) for entry in matching):
            return URL_TRUSTED
        if any(entry.state == SOURCE_STATE_PROPOSED for entry in matching):
            return URL_PROPOSED
        return None

    def trusted_patterns(self, product: str | None = None) -> list[str]:
        return sorted(
            {entry.pattern for entry in self.entries if entry.state == SOURCE_STATE_TRUSTED and entry.covers(product)}
        )

    def trusted_hosts(self, product: str | None = None) -> list[str]:
        """The hosts to restrict a search provider to; path prefixes are enforced afterwards."""
        return sorted({pattern_host(pattern) for pattern in self.trusted_patterns(product)})

    def blocked_hosts(self) -> list[str]:
        return sorted({pattern_host(entry.pattern) for entry in self.entries if entry.state == SOURCE_STATE_BLOCKED})


def scope_key(project_id: str | None) -> str:
    return project_id or SCOPE_PLATFORM


def normalize_products(raw: object) -> list[str]:
    values = raw if isinstance(raw, list) else []
    products: list[str] = []
    for value in values[:MAX_PRODUCTS]:
        product = str(value or "").strip().lower()
        if not _PRODUCT.match(product):
            raise InvalidSourcePatternError("invalid_product")
        if product not in products:
            products.append(product)
    return products


async def _rows(db: AsyncSession, project_id: str | None) -> list[WebTrustedSource]:
    scopes = [SCOPE_PLATFORM] + ([project_id] if project_id else [])
    statement = (
        select(WebTrustedSource)
        .where(WebTrustedSource.scope_key.in_(scopes))
        .order_by(WebTrustedSource.scope_key, WebTrustedSource.pattern)
    )
    return list((await db.execute(statement)).scalars().all())


async def load_policy(db: AsyncSession, *, project_id: str | None) -> SourcePolicy:
    return SourcePolicy(
        tuple(
            SourceEntry(row.pattern, tuple(row.products or ()), row.state, row.scope_key)
            for row in await _rows(db, project_id)
        )
    )


async def list_sources(db: AsyncSession, *, project_id: str | None) -> list[WebTrustedSource]:
    return await _rows(db, project_id)


async def _existing(db: AsyncSession, scope: str, pattern: str) -> WebTrustedSource | None:
    statement = select(WebTrustedSource).where(WebTrustedSource.scope_key == scope, WebTrustedSource.pattern == pattern)
    return (await db.execute(statement)).scalars().first()


async def _count(db: AsyncSession, scope: str) -> int:
    rows = await db.execute(select(WebTrustedSource.id).where(WebTrustedSource.scope_key == scope))
    return len(rows.all())


async def put_source(
    db: AsyncSession,
    *,
    project_id: str | None,
    pattern: object,
    state: str,
    products: object = None,
    reason: object = "",
    user_id: str | None,
) -> WebTrustedSource:
    """An admin's entry: creates it, or re-decides an existing one in the same scope."""
    if state not in SOURCE_STATES:
        raise InvalidSourcePatternError("invalid_state")
    canonical = normalize_pattern(pattern)
    scope = scope_key(project_id)
    row = await _existing(db, scope, canonical)
    if row is None:
        if await _count(db, scope) >= MAX_ENTRIES_PER_SCOPE:
            raise InvalidSourcePatternError("too_many_entries")
        row = WebTrustedSource(
            scope_key=scope, project_id=project_id, pattern=canonical, origin=ORIGIN_ADMIN, created_by=user_id
        )
        db.add(row)
    row.state = state
    row.products = normalize_products(products)
    row.reason = " ".join(str(reason or "").split())[:MAX_REASON_CHARS]
    if state != SOURCE_STATE_PROPOSED:
        row.decided_by, row.decided_at = user_id, utc_now()
    await db.flush()
    return row


async def decide_source(db: AsyncSession, row: WebTrustedSource, *, state: str, user_id: str | None) -> None:
    if state not in (SOURCE_STATE_TRUSTED, SOURCE_STATE_BLOCKED):
        raise InvalidSourcePatternError("invalid_state")
    row.state, row.decided_by, row.decided_at = state, user_id, utc_now()
    await db.flush()


async def propose_sources(
    db: AsyncSession, *, project_id: str, proposals: list[tuple[str, str, str, str | None]]
) -> list[str]:
    """Agent proposals ``(pattern, evidence_url, reason, product)``; returns the patterns recorded.

    A proposal is recorded only when the registry does not decide the evidence URL yet, so an agent
    can never re-open a source an admin trusted or blocked.
    """
    policy = await load_policy(db, project_id=project_id)
    recorded: list[str] = []
    for raw_pattern, evidence_url, reason, product in proposals:
        try:
            canonical = normalize_pattern(raw_pattern)
        except InvalidSourcePatternError:
            continue
        if canonical in recorded or policy.state_of(evidence_url, product) is not None:
            continue
        if await _count(db, project_id) >= MAX_ENTRIES_PER_SCOPE:
            break
        db.add(
            WebTrustedSource(
                scope_key=project_id,
                project_id=project_id,
                pattern=canonical,
                products=[product] if product and _PRODUCT.match(product) else [],
                state=SOURCE_STATE_PROPOSED,
                origin=ORIGIN_AGENT,
                reason=" ".join(str(reason or "").split())[:MAX_REASON_CHARS],
                evidence_url=evidence_url[:2048],
            )
        )
        recorded.append(canonical)
    await db.flush()
    return recorded


async def source_in_scope(db: AsyncSession, *, source_id: str, project_id: str | None) -> WebTrustedSource | None:
    statement = select(WebTrustedSource).where(
        WebTrustedSource.id == source_id,
        or_(WebTrustedSource.scope_key == scope_key(project_id), WebTrustedSource.scope_key == SCOPE_PLATFORM),
    )
    return (await db.execute(statement)).scalars().first()


__all__ = [
    "SourceEntry",
    "SourcePolicy",
    "URL_BLOCKED",
    "URL_PROPOSED",
    "URL_TRUSTED",
    "decide_source",
    "list_sources",
    "load_policy",
    "normalize_products",
    "propose_sources",
    "put_source",
    "scope_key",
    "source_in_scope",
]
