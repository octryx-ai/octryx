"""Provider client kwargs builders for control-plane runtimes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider
from .provider_auth import PROVIDER_CREDENTIAL


def _gateway_default_admission() -> Any:
    from ..model_gateway.litellm.project_admission import (
        PROJECT_ADMISSION_KWARG,
        UNVERIFIED_PROJECT_ADMISSION,
    )

    return {PROJECT_ADMISSION_KWARG: UNVERIFIED_PROJECT_ADMISSION}


async def _resolve_gateway_virtual_key(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    get_secret_value_func: Any,
) -> str | None:
    secret_ref = str(getattr(provider, "api_key_secret_ref", "") or "").strip()
    if not secret_ref:
        return None
    value = await get_secret_value_func(db, secret_id=secret_ref, purpose=PROVIDER_CREDENTIAL)
    return str(value or "").strip() or None


def build_provider_client_kwargs(
    provider: LLMProvider | None,
    *,
    settings: Any,
    infer_provider_runtime_func: Any,
    get_provider_auth_mode_func: Any,
) -> dict[str, Any]:
    if not provider:
        # No provider: the factory refuses the empty driver.
        return {"provider_name": "", "driver": "", "endpoint_url": None, "api_key": None, "auth_mode": "api_key"}
    runtime = infer_provider_runtime_func(
        name=provider.name,
        driver=getattr(provider, "driver", None),
        provider_family=getattr(provider, "provider_family", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        auth_mode=provider.auth_mode,
    )
    kwargs: dict[str, Any] = {
        "provider_name": provider.name,
        "driver": runtime["driver"],
        "provider_family": runtime["provider_family"],
        "runtime_kind": runtime["runtime_kind"],
        "endpoint_url": getattr(provider, "endpoint_url", None),
        "config_json": getattr(provider, "config_json", None),
        "capabilities_json": getattr(provider, "capabilities_json", None),
        "api_key": None,
        "auth_mode": get_provider_auth_mode_func(provider),
    }
    if runtime["driver"] == "litellm_gateway":
        kwargs.update(_gateway_default_admission())
    return kwargs


async def build_provider_client_kwargs_async(
    db: AsyncSession,
    provider: LLMProvider | None,
    *,
    build_provider_client_kwargs_func: Any,
    get_secret_value_func: Any,
) -> dict[str, Any]:
    kwargs = build_provider_client_kwargs_func(provider)
    if provider is not None and kwargs.get("driver") == "litellm_gateway":
        kwargs["api_key"] = await _resolve_gateway_virtual_key(db, provider, get_secret_value_func=get_secret_value_func)
    return kwargs


__all__ = ["build_provider_client_kwargs", "build_provider_client_kwargs_async"]
