"""Provider credential writes that go through the secret store instead of the provider row."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from ...control_plane.provider_auth import provider_secret_scope
from ...provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata

BEDROCK_STATIC_CREDENTIAL_FIELDS = ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")


async def _store_provider_api_key(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    raw_value: Any,
    set_secret_value_func: Callable[..., Any] | None,
) -> None:
    api_key = str(raw_value or "").strip()
    if not api_key:
        return
    if set_secret_value_func is None:
        # No plaintext storage path exists: fall back to the canonical
        # secret writer instead of persisting the key on the provider row.
        from ...secret import set_secret_value as set_secret_value_func
    secret_tool_name, secret_field_name = provider_secret_scope(provider, "api_key")
    secret_entry = await set_secret_value_func(
        db,
        tool_name=secret_tool_name,
        field_name=secret_field_name,
        project_id=None,
        value=api_key,
    )
    secret_id = getattr(secret_entry, "id", None)
    if secret_id:
        provider.api_key_secret_ref = str(secret_id)


async def _store_provider_secrets(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    set_secret_value_func: Callable[..., Any] | None,
) -> None:
    if not set_secret_value_func:
        return
    stored_fields: set[str] = set()
    for field_name in field_names:
        if payload.get(field_name) is None:
            continue
        raw_value = str(payload.get(field_name) or "").strip()
        if not raw_value:
            continue
        secret_tool_name, secret_field_name = provider_secret_scope(provider, field_name)
        await set_secret_value_func(
            db,
            tool_name=secret_tool_name,
            field_name=secret_field_name,
            project_id=None,
            value=raw_value,
        )
        stored_fields.add(field_name)
    if {"aws_access_key_id", "aws_secret_access_key"}.issubset(stored_fields):
        meta = await read_oauth_metadata(db, provider)
        meta["aws_static_credentials_configured"] = True
        await write_oauth_metadata(db, provider, meta)


async def store_google_client_secret(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    google_client_secret: str,
    set_secret_value_func: Callable[..., Any],
) -> None:
    secret_tool_name, secret_field_name = provider_secret_scope(
        provider,
        "google_oauth_client_secret",
    )
    await set_secret_value_func(
        db,
        tool_name=secret_tool_name,
        field_name=secret_field_name,
        project_id=None,
        value=google_client_secret,
    )
