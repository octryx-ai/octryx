from __future__ import annotations

import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.providers import get_provider as get_provider_client
from ...agent.providers import infer_provider_runtime, provider_supports_model_sync
from ...models import LLMModel, LLMProvider
from ...schemas.operations.provider import ModelResponse, ProviderCreate, ProviderResponse
from ...services.control_plane.provider_auth import provider_secret_scope
from ...services.secret import set_secret_value
from ...time_utils import utc_now
from .driver_policy import require_supported_driver
from .model_sync import (
    apply_model_sync_provider_metadata,
    model_sync_failure_payload,
    model_sync_no_models_payload,
    model_sync_success_payload,
    normalize_model_catalog_payload,
    raise_model_sync_http_error,
)

BuildProviderClientKwargs = Callable[[AsyncSession, LLMProvider], Awaitable[dict[str, object]]]
ProviderSyncResponse = dict[str, Any]


async def list_provider_responses(db: AsyncSession) -> list[ProviderResponse]:
    providers = await _list_providers(db)
    model_counts = await _list_provider_model_counts(db)
    return [_serialize_provider(provider, model_counts.get(provider.id, 0)) for provider in providers]


async def create_provider_response(db: AsyncSession, body: ProviderCreate, current_user) -> ProviderResponse:
    # Same write-boundary decision as the admin panel path: an unsupported driver is
    # refused before a row or a secret exists.
    provider = _build_provider(body, driver=require_supported_driver(body.driver))
    if body.api_key:
        secret_tool_name, secret_field_name = provider_secret_scope(provider, "api_key")
        secret_entry = await set_secret_value(
            db,
            tool_name=secret_tool_name,
            field_name=secret_field_name,
            project_id=None,
            value=body.api_key,
        )
        provider.api_key_secret_ref = secret_entry.id
    db.add(provider)
    await db.commit()
    return _serialize_provider(provider, 0)


async def list_active_provider_models(db: AsyncSession, *, provider_id: str) -> list[ModelResponse]:
    models = await _list_active_models(db, provider_id=provider_id)
    return [_serialize_model(model) for model in models]


async def sync_provider_models(
    db: AsyncSession,
    *,
    provider_id: str,
    build_provider_client_kwargs_async_func: BuildProviderClientKwargs,
) -> ProviderSyncResponse:
    provider = await _get_provider_or_404(db, provider_id=provider_id)
    supports_model_sync = provider_supports_model_sync(driver=provider.driver)
    if not supports_model_sync:
        total_models, active_models = await _provider_model_counts(db, provider_id=provider.id)
        response = model_sync_no_models_payload(
            total_models=total_models,
            active_models=active_models,
            provider_supports_model_sync=False,
        )
        apply_model_sync_provider_metadata(provider, response, checked_at=utc_now())
        await db.commit()
        return response

    try:
        models_added, models_seen, models_ignored = await _sync_provider_models_from_runtime(
            db,
            provider=provider,
            build_provider_client_kwargs_async_func=build_provider_client_kwargs_async_func,
        )
    except Exception as exc:
        total_models, active_models = await _provider_model_counts(db, provider_id=provider.id)
        response = model_sync_failure_payload(
            exc,
            total_models=total_models,
            active_models=active_models,
        )
        apply_model_sync_provider_metadata(provider, response, checked_at=utc_now())
        await db.commit()
        raise_model_sync_http_error(response)

    total_models, active_models = await _provider_model_counts(db, provider_id=provider.id)
    if models_seen == 0:
        response = model_sync_no_models_payload(
            total_models=total_models,
            active_models=active_models,
            provider_supports_model_sync=True,
        )
    else:
        response = model_sync_success_payload(
            models_added=models_added,
            models_seen=models_seen,
            models_ignored=models_ignored,
            total_models=total_models,
            active_models=active_models,
        )
    apply_model_sync_provider_metadata(provider, response, checked_at=utc_now())
    await db.commit()
    return response


async def _list_providers(db: AsyncSession) -> list[LLMProvider]:
    return (await db.execute(select(LLMProvider).order_by(LLMProvider.name))).scalars().all()


async def _list_provider_model_counts(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(select(LLMModel.provider_id, func.count(LLMModel.id)).group_by(LLMModel.provider_id))
    return {provider_id: model_count for provider_id, model_count in rows.all()}


async def _provider_model_counts(db: AsyncSession, *, provider_id: str) -> tuple[int, int]:
    rows = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider_id,
            )
        )
    ).scalars().all()
    return len(rows), sum(1 for model in rows if model.is_active)


def _build_provider(body: ProviderCreate, *, driver: str) -> LLMProvider:
    # api_key never lands on the row; the caller stores it encrypted as a secret.
    runtime = infer_provider_runtime(
        name=body.name,
        driver=driver,
        provider_family=body.provider_family,
        runtime_kind=body.runtime_kind,
        auth_mode=body.auth_mode,
    )
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name=runtime["name"],
        provider_family=runtime["provider_family"],
        driver=runtime["driver"],
        runtime_kind=runtime["runtime_kind"],
        display_name=body.display_name or runtime["name"],
        profile_name=body.profile_name,
        endpoint_url=body.endpoint_url,
        binary_path=body.binary_path,
        auth_mode=runtime["auth_mode"],
        aws_region=body.aws_region,
        aws_role_arn=body.aws_role_arn,
        is_global=body.is_global,
        project_id=body.project_id,
    )
    provider.config_json = dict(body.config_json or {}) or None
    return provider


async def _list_active_models(db: AsyncSession, *, provider_id: str) -> Sequence[LLMModel]:
    return (
        (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.provider_id == provider_id,
                    LLMModel.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


async def _get_provider_or_404(db: AsyncSession, *, provider_id: str) -> LLMProvider:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


def _resolve_provider_client() -> Callable[..., object]:
    root_module = sys.modules.get("app.services.provider")
    if root_module is not None and hasattr(root_module, "get_provider_client"):
        return root_module.get_provider_client
    return get_provider_client


async def _sync_provider_models_from_runtime(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    build_provider_client_kwargs_async_func: BuildProviderClientKwargs,
) -> tuple[int, int, int]:
    client_factory = _resolve_provider_client()
    client = None
    models_added = 0
    models_seen = 0
    models_ignored = 0
    try:
        client = client_factory(**(await build_provider_client_kwargs_async_func(db, provider)))
        raw_models = await client.list_models()
        models, models_ignored = normalize_model_catalog_payload(raw_models)
        models_seen = len(models)
        for model_payload in models:
            added_model = await _create_synced_model_if_missing(
                db,
                provider=provider,
                model_payload=model_payload,
            )
            if added_model is not None:
                db.add(added_model)
                models_added += 1
    finally:
        if client is not None:
            await client.close()
    await db.flush()
    return models_added, models_seen, models_ignored


async def _create_synced_model_if_missing(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    model_payload: dict[str, object],
) -> LLMModel | None:
    model_id = model_payload.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None

    existing = await db.execute(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.model_id == model_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    display_name = model_payload.get("name")
    context_length = model_payload.get("context_length")
    return LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id=model_id,
        display_name=display_name if isinstance(display_name, str) else model_id,
        context_length=context_length if isinstance(context_length, int) else None,
        supports_streaming=True,
        supports_tools=bool(model_payload.get("supports_tools", False)),
        supports_vision=bool(model_payload.get("supports_vision", False)),
    )


def _serialize_provider(provider: LLMProvider, model_count: int) -> ProviderResponse:
    return ProviderResponse(
        id=provider.id,
        name=provider.name,
        provider_family=getattr(provider, "provider_family", None),
        driver=getattr(provider, "driver", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        display_name=provider.display_name or provider.name,
        profile_name=getattr(provider, "profile_name", None),
        endpoint_url=getattr(provider, "endpoint_url", None),
        binary_path=getattr(provider, "binary_path", None),
        auth_mode=getattr(provider, "auth_mode", None),
        is_active=provider.is_active,
        is_global=provider.is_global,
        project_id=provider.project_id,
        created_at=provider.created_at.isoformat(),
        model_count=model_count,
    )


def _serialize_model(model: LLMModel) -> ModelResponse:
    return ModelResponse(
        id=model.id,
        provider_id=model.provider_id,
        model_id=model.model_id,
        display_name=model.display_name,
        supports_tools=model.supports_tools,
        supports_vision=model.supports_vision,
        supports_streaming=model.supports_streaming,
        context_length=model.context_length,
        pricing_input=model.pricing_input,
        pricing_output=model.pricing_output,
        is_active=model.is_active,
    )


__all__ = [
    "BuildProviderClientKwargs",
    "ProviderSyncResponse",
    "create_provider_response",
    "list_active_provider_models",
    "list_provider_responses",
    "sync_provider_models",
]
