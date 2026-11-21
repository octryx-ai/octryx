"""Read / write helpers for provider OAuth configuration.

The backing store is the normalized ``provider_oauth_config`` table (1:1 with
``llm_providers`` via a unique ``provider_id``). These helpers are the single
read/write path for the six OAuth flows.

Callers operate on a plain ``dict``; these helpers map it to and from the
``provider_oauth_config`` row.

The helpers are ``async`` and load the ``provider_oauth_config`` row explicitly
via the session, because these callers hold an ``AsyncSession`` where lazy
relationship access would raise ``MissingGreenlet``. Sync call sites (serializers,
readiness, audit snapshots) instead read the eager-loaded
``provider.oauth_config`` relationship via
:func:`app.models.runtime.provider_oauth_config.oauth_metadata_from_provider`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider, ProviderOAuthConfig
from ...models.runtime.provider_oauth_config import (
    oauth_config_columns_from_metadata,
    oauth_config_to_metadata,
)


async def _load_config(db: AsyncSession, provider: LLMProvider) -> ProviderOAuthConfig | None:
    return (
        await db.execute(
            select(ProviderOAuthConfig).where(ProviderOAuthConfig.provider_id == provider.id)
        )
    ).scalar_one_or_none()


def _set_relationship(provider: LLMProvider, config: ProviderOAuthConfig | None) -> None:
    """Keep the in-session ``provider.oauth_config`` relationship consistent.

    Sync readers (serializers, readiness, audit snapshots) read this eager
    attribute, so writers assign it directly. Assigning also primes the
    attribute in ``provider.__dict__``, so a later sync read never falls through
    to an async lazy load (which would raise ``MissingGreenlet``).
    """

    provider.oauth_config = config


async def read_oauth_metadata(db: AsyncSession, provider: LLMProvider) -> dict[str, Any]:
    """Resolve the effective OAuth metadata mapping for ``provider``.

    Reads the ``provider_oauth_config`` row and always returns a plain dict
    (never the ORM-attached instance) so callers can mutate freely. Returns an
    empty dict when the provider has no config row yet.
    """

    config = await _load_config(db, provider)
    if config is not None:
        return oauth_config_to_metadata(config)
    return {}


async def write_oauth_metadata(db: AsyncSession, provider: LLMProvider, meta: dict[str, Any]) -> None:
    """Persist ``meta`` to the ``provider_oauth_config`` row (upsert)."""

    normalized = dict(meta or {})
    columns = oauth_config_columns_from_metadata(normalized)
    config = await _load_config(db, provider)
    if config is None:
        config = ProviderOAuthConfig(provider_id=provider.id)
        db.add(config)
    for key, value in columns.items():
        setattr(config, key, value)
    _set_relationship(provider, config)


async def clear_oauth_metadata(db: AsyncSession, provider: LLMProvider) -> None:
    """Reset OAuth metadata by deleting the ``provider_oauth_config`` row.

    So a reset (e.g. switching Copilot back to ``auth_session``) does not leave
    stale normalized state behind.
    """

    config = await _load_config(db, provider)
    if config is not None:
        await db.delete(config)
    _set_relationship(provider, None)
