"""Read / write helpers for provider OAuth configuration."""

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
    provider.oauth_config = config


async def read_oauth_metadata(db: AsyncSession, provider: LLMProvider) -> dict[str, Any]:
    """Resolve the effective OAuth metadata mapping for ``provider``."""

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


