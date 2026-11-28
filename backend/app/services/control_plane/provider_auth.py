"""Provider auth and secret resolution helpers for control plane."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider

CONTROL_PLANE_PROVIDER_TOOL_PREFIX = "control_plane_provider"
DEFAULT_PROVIDER_SECRET_KEY = "default"
PROVIDER_CREDENTIAL = "provider.credential"


def provider_secret_tool_name(provider: LLMProvider | None) -> str:
    provider_key = provider.id if provider else DEFAULT_PROVIDER_SECRET_KEY
    return f"{CONTROL_PLANE_PROVIDER_TOOL_PREFIX}:{provider_key}"


def provider_secret_scope(provider: LLMProvider | None, field_name: str = "api_key") -> tuple[str, str]:
    return (provider_secret_tool_name(provider), field_name)


async def resolve_provider_api_key(
    db: AsyncSession,
    provider: LLMProvider | None,
    *,
    settings: Any,
    get_secret_value_func: Any,
) -> str | None:
    if not provider:
        return settings.openrouter_api_key
    if getattr(provider, "api_key_secret_ref", None):
        secret_value = await get_secret_value_func(db, secret_id=provider.api_key_secret_ref, purpose=PROVIDER_CREDENTIAL)
        if secret_value:
            return secret_value
    tool_name, field_name = provider_secret_scope(provider)
    return await get_secret_value_func(db, tool_name=tool_name, field_name=field_name, project_id=None,
                                       purpose=PROVIDER_CREDENTIAL)


def get_provider_auth_mode(provider: LLMProvider | None) -> str:
    return str(getattr(provider, "auth_mode", "") or "").strip().lower() or "api_key"
