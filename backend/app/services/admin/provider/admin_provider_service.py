"""Admin-panel service helpers for provider and model management flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....agent.providers import infer_provider_runtime, provider_supports_model_sync
from ....models import (
    ControlPlaneConfig,
    ControlPlaneRuntimeTarget,
    LLMModel,
    LLMProvider,
    UserProviderToken,
)
from ...provider.driver_policy import require_supported_driver
from ..governance.admin_config_audit_service import record_admin_config_audit
from ._admin_provider_fields import (
    apply_aws_and_active_fields,
    apply_descriptive_fields,
    apply_runtime_fields,
    build_provider_row,
)
from ._admin_provider_secrets import _store_provider_api_key
from ._admin_provider_snapshots import _provider_audit_snapshot, serialize_model
from ._admin_provider_sync import ModelSyncTally, apply_synced_catalog, finish_model_sync, record_sync_failure


async def list_providers(
    db: AsyncSession,
    *,
    serialize_provider: Callable[[LLMProvider, int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(LLMProvider).options(selectinload(LLMProvider.oauth_config)).order_by(LLMProvider.name)
    )
    providers = result.scalars().all()
    payloads: list[dict[str, Any]] = []
    for provider in providers:
        all_models = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id))).scalars().all()
        active = sum(1 for model in all_models if model.is_active)
        payloads.append(serialize_provider(provider, len(all_models), active))
    return payloads


async def create_provider(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    serialize_provider: Callable[[LLMProvider, int, int], dict[str, Any]],
    set_secret_value_func: Callable[..., Any] | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    # Fail closed before any row, secret or audit record exists: a provider names one
    # supported driver id, and only that id selects its runtime.
    driver = require_supported_driver(payload.get("driver"))
    runtime = infer_provider_runtime(
        name=payload.get("name"),
        driver=driver,
        provider_family=payload.get("provider_family"),
        runtime_kind=payload.get("runtime_kind"),
        auth_mode=payload.get("auth_mode"),
    )
    provider = build_provider_row(payload, runtime=runtime, auth_mode=runtime["auth_mode"])
    # Prime the eager relationship so sync readers (audit snapshot, serializer)
    # never fall through to an async lazy load on this freshly-built provider.
    provider.oauth_config = None
    db.add(provider)
    if payload.get("api_key") is not None:
        await _store_provider_api_key(
            db,
            provider,
            raw_value=payload.get("api_key"),
            set_secret_value_func=set_secret_value_func,
        )
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.created",
        resource_type="provider_config",
        resource_id=provider.id,
        project_id=None,
        before=None,
        after=_provider_audit_snapshot(provider),
        details={"operation": "create_provider", "payload_keys": sorted(str(key) for key in payload)},
    )
    await db.commit()
    return serialize_provider(provider, 0, 0)


async def _load_provider_with_oauth(db: AsyncSession, provider_id: str) -> LLMProvider:
    provider = (
        await db.execute(
            select(LLMProvider)
            .where(LLMProvider.id == provider_id)
            .options(selectinload(LLMProvider.oauth_config))
        )
    ).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


async def update_provider(
    db: AsyncSession,
    *,
    provider_id: str,
    payload: dict[str, Any],
    serialize_provider: Callable[[LLMProvider, int, int], dict[str, Any]],
    set_secret_value_func: Callable[..., Any] | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    provider = await _load_provider_with_oauth(db, provider_id)
    # An update that restates the driver must name a supported one; it is refused
    # before the first field is touched.
    if payload.get("driver") is not None:
        payload = {**payload, "driver": require_supported_driver(payload.get("driver"))}
    before = _provider_audit_snapshot(provider)
    apply_descriptive_fields(provider, payload)
    apply_runtime_fields(provider, payload)
    if payload.get("api_key") is not None:
        await _store_provider_api_key(
            db,
            provider,
            raw_value=payload.get("api_key"),
            set_secret_value_func=set_secret_value_func,
        )
    apply_aws_and_active_fields(provider, payload)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.updated",
        resource_type="provider_config",
        resource_id=provider.id,
        project_id=None,
        before=before,
        after=_provider_audit_snapshot(provider),
        details={"operation": "update_provider", "payload_keys": sorted(str(key) for key in payload)},
    )
    await db.commit()
    provider_models = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id))).scalars().all()
    count = len(provider_models)
    active = len([model for model in provider_models if model.is_active])
    return serialize_provider(provider, count, active)


async def delete_provider(db: AsyncSession, *, provider_id: str, actor_user_id: str | None = None) -> dict[str, Any]:
    provider = await _load_provider_with_oauth(db, provider_id)
    before = _provider_audit_snapshot(provider)
    # Remove all FK-dependent rows before deleting the provider
    await db.execute(sa_delete(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.provider_id == provider_id))
    await db.execute(sa_delete(UserProviderToken).where(UserProviderToken.provider_id == provider_id))
    await db.execute(sa_delete(LLMModel).where(LLMModel.provider_id == provider_id))
    # Null out nullable FK in control_plane_config
    result = await db.execute(select(ControlPlaneConfig).where(ControlPlaneConfig.provider_id == provider_id))
    for config in result.scalars().all():
        config.provider_id = None
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.deleted",
        resource_type="provider_config",
        resource_id=provider_id,
        project_id=None,
        before=before,
        after=None,
        details={"operation": "delete_provider"},
    )
    await db.delete(provider)
    await db.commit()
    return {"status": "deleted"}


async def list_provider_models(db: AsyncSession, *, provider_id: str) -> list[dict[str, Any]]:
    result = await db.execute(
        select(LLMModel).where(LLMModel.provider_id == provider_id).order_by(LLMModel.display_name)
    )
    return [serialize_model(model) for model in result.scalars().all()]


async def sync_provider_models(
    db: AsyncSession,
    *,
    provider_id: str,
    build_provider_client_kwargs_async_func: Callable[..., Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    before_models = (
        await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id).order_by(LLMModel.model_id))
    ).scalars().all()
    tally = ModelSyncTally()
    supports_model_sync = provider_supports_model_sync(driver=provider.driver)
    if supports_model_sync:
        from ....agent.providers import get_provider as get_provider_client
        client = None
        try:
            client = get_provider_client(**(await build_provider_client_kwargs_async_func(db, provider)))
            raw_models = await client.list_models()
            await apply_synced_catalog(db, provider, raw_models, before_models=before_models, tally=tally)
        except Exception as exc:
            await record_sync_failure(
                db,
                provider,
                exc,
                before_models=before_models,
                supports_model_sync=supports_model_sync,
                actor_user_id=actor_user_id,
            )
        finally:
            if client is not None:
                await client.close()
    return await finish_model_sync(
        db,
        provider,
        before_models=before_models,
        tally=tally,
        supports_model_sync=supports_model_sync,
        actor_user_id=actor_user_id,
    )
