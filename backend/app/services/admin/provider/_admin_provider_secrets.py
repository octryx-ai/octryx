"""Provider credential writes that go through the secret store instead of the provider row."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from ...control_plane.provider_auth import provider_secret_scope


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
