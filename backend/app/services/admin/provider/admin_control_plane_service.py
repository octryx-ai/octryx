"""Service helpers for the control-plane admin page actions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....agent.providers import infer_provider_runtime, provider_supports_model_sync
from ....models import LLMModel, LLMProvider
from ...control_plane.config import resolve_control_plane_promoted_model
from ...provider.driver_policy import require_supported_driver
from ...provider.oauth_config_bridge import clear_oauth_metadata


async def save_control_plane_provider(
    db: AsyncSession,
    *,
    provider_id: str,
    driver: str,
    display_name: str,
    auth_mode: str,
    api_key: str,
    aws_region: str,
    aws_role_arn: str,
    is_active: bool,
    set_as_active: bool,
    model_id: str,
    sync_models: bool,
    ensure_control_plane_defaults_func: Callable[..., Any],
    upsert_runtime_target_func: Callable[..., Any],
    sync_primary_runtime_target_func: Callable[..., Any],
    provider_secret_scope_func: Callable[[LLMProvider], tuple[str, str]],
    set_secret_value_func: Callable[..., Any],
    build_provider_client_kwargs_async_func: Callable[..., Any],
    get_provider_func: Callable[..., Any],
    default_model_id: str,
) -> str:
    canonical_driver = require_supported_driver(driver)
    provider, previous_driver = await _load_or_create_provider(db, provider_id)

    await _configure_provider(
        db, provider, driver=canonical_driver, display_name=display_name, auth_mode=auth_mode,
        api_key=api_key, aws_region=aws_region, aws_role_arn=aws_role_arn,
        previous_driver=previous_driver,
        provider_secret_scope_func=provider_secret_scope_func, set_secret_value_func=set_secret_value_func,
    )

    provider.default_model_id = model_id.strip() or None
    provider.is_global = True
    provider.is_active = is_active
    await db.flush()

    config = await ensure_control_plane_defaults_func(db)
    if set_as_active:
        await _promote_provider_target(
            db, provider, config=config, default_model_id=default_model_id,
            upsert_runtime_target_func=upsert_runtime_target_func,
        )
    else:
        await sync_primary_runtime_target_func(db, config)
    config.is_active = True

    if sync_models and provider_supports_model_sync(driver=provider.driver):
        client = get_provider_func(**(await build_provider_client_kwargs_async_func(db, provider)))
        try:
            await _store_listed_models(db, provider, await client.list_models())
        finally:
            await client.close()

    await db.commit()
    return provider.id


async def _load_or_create_provider(db: AsyncSession, provider_id: str) -> tuple[LLMProvider, str | None]:
    provider: LLMProvider | None = None
    if provider_id:
        provider = await db.get(LLMProvider, provider_id)
    previous_driver = provider.driver if provider else None
    if not provider:
        provider = LLMProvider(id=str(uuid.uuid4()), is_global=True, is_active=True)
        db.add(provider)
    return provider, previous_driver


async def _promote_provider_target(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    config: Any,
    default_model_id: str,
    upsert_runtime_target_func: Callable[..., Any],
) -> None:
    target_model_id = (
        resolve_control_plane_promoted_model(
            provider,
            config=config,
            fallback_model_id=default_model_id,
        )
        or default_model_id
    )
    await upsert_runtime_target_func(
        db,
        provider=provider,
        model_id=target_model_id,
        make_primary=True,
        is_active=True,
    )


async def _configure_provider(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    driver: str,
    display_name: str,
    auth_mode: str,
    api_key: str,
    aws_region: str,
    aws_role_arn: str,
    previous_driver: str | None,
    provider_secret_scope_func: Callable[[LLMProvider], tuple[str, str]],
    set_secret_value_func: Callable[..., Any],
) -> None:
    runtime = infer_provider_runtime(driver=driver, name=provider.name)
    _apply_provider_runtime(provider, runtime, display_name=display_name)
    provider.auth_mode = _provider_auth_mode(runtime, auth_mode)
    await _apply_provider_secret(
        db,
        provider,
        runtime,
        api_key=api_key,
        previous_driver=previous_driver,
        provider_secret_scope_func=provider_secret_scope_func,
        set_secret_value_func=set_secret_value_func,
    )
    _apply_provider_location(provider, runtime, aws_region=aws_region, aws_role_arn=aws_role_arn)


def _apply_provider_runtime(provider: LLMProvider, runtime: dict[str, Any], *, display_name: str) -> None:
    provider.name = runtime["name"]
    provider.provider_family = runtime["provider_family"]
    provider.driver = runtime["driver"]
    provider.runtime_kind = runtime["runtime_kind"]
    provider.display_name = (display_name or runtime["name"]).strip()


def _provider_auth_mode(runtime: dict[str, Any], auth_mode: str) -> str:
    normalized_auth_mode = auth_mode.strip().lower() or "api_key"
    if runtime["driver"] == "copilot_api":
        return normalized_auth_mode if normalized_auth_mode in {"api_key", "auth_session", "oauth"} else "auth_session"
    if runtime["driver"] == "bedrock_api":
        return "aws_role"
    if runtime["driver"] == "ollama":
        return "none"
    if runtime["runtime_kind"] == "cli":
        return "profile"
    return "api_key"


async def _apply_provider_secret(
    db: AsyncSession,
    provider: LLMProvider,
    runtime: dict[str, Any],
    *,
    api_key: str,
    previous_driver: str | None,
    provider_secret_scope_func: Callable[[LLMProvider], tuple[str, str]],
    set_secret_value_func: Callable[..., Any],
) -> None:
    if runtime["driver"] == "bedrock_api":
        provider.api_key_secret_ref = None
        return
    new_secret_value = api_key.strip()
    if runtime["driver"] == "copilot_api" and provider.auth_mode == "auth_session":
        provider.api_key_secret_ref = None
        await clear_oauth_metadata(db, provider)
    elif runtime["driver"] == "copilot_api" and provider.auth_mode == "oauth" and not new_secret_value:
        pass
    elif new_secret_value:
        tool_name, field_name = provider_secret_scope_func(provider)
        secret_entry = await set_secret_value_func(
            db,
            tool_name=tool_name,
            field_name=field_name,
            project_id=None,
            value=new_secret_value,
        )
        provider.api_key_secret_ref = secret_entry.id
    elif previous_driver != provider.driver:
        provider.api_key_secret_ref = None


def _apply_provider_location(
    provider: LLMProvider, runtime: dict[str, Any], *, aws_region: str, aws_role_arn: str
) -> None:
    if runtime["driver"] == "bedrock_api":
        provider.aws_region = aws_region.strip() or None
        provider.aws_role_arn = aws_role_arn.strip() or None
    else:
        provider.aws_region = None
        provider.aws_role_arn = None


async def _store_listed_models(db: AsyncSession, provider: LLMProvider, models: list[dict[str, Any]]) -> None:
    for item in models:
        existing = await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.model_id == item["id"],
            )
        )
        if existing.scalar_one_or_none():
            continue
        db.add(
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=provider.id,
                model_id=item["id"],
                display_name=item.get("name", item["id"]),
                context_length=item.get("context_length"),
                supports_streaming=True,
                supports_tools=True,
            )
        )
    await db.commit()


__all__ = ["save_control_plane_provider"]
