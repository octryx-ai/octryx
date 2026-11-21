"""Internal lifecycle workflows for local bootstrap service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from ..provider import resolve_provider_readiness
from ..provider_runtime_config import resolve_provider_default_model
from .bootstrap_state import serialize_bootstrap_state


async def _status_provider(db: AsyncSession) -> LLMProvider | None:
    return (
        (
            await db.execute(
                select(LLMProvider)
                .where(
                    LLMProvider.driver == "ollama",
                    LLMProvider.is_global,
                )
                .order_by(
                    (LLMProvider.bootstrap_role == "default_anchor").desc(),
                    LLMProvider.updated_at.desc(),
                )
            )
        )
        .scalars()
        .first()
    )


async def get_local_bootstrap_status(
    db: AsyncSession,
    *,
    default_local_bootstrap_model: str,
    default_local_bootstrap_display_name: str,
    default_local_bootstrap_profile: str,
    default_ollama_base_url_func,
    get_or_create_control_plane_config_func,
) -> dict[str, Any]:
    provider = await _status_provider(db)
    runtime_target = None
    installed_model = None
    resolved_model_id = default_local_bootstrap_model
    if provider:
        config = await get_or_create_control_plane_config_func(db)
        resolved_model_id = (
            resolve_provider_default_model(
                provider,
                config=config,
                fallback_model_id=default_local_bootstrap_model,
            )
            or default_local_bootstrap_model
        )
        runtime_target = (
            (
                await db.execute(
                    select(ControlPlaneRuntimeTarget).where(
                        ControlPlaneRuntimeTarget.config_id == config.id,
                        ControlPlaneRuntimeTarget.provider_id == provider.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        installed_model = (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.provider_id == provider.id,
                    LLMModel.model_id == resolved_model_id,
                )
            )
        ).scalar_one_or_none()
    return serialize_bootstrap_state(
        provider=provider,
        runtime_target=runtime_target,
        installed_model=installed_model,
        resolved_model_id=resolved_model_id,
        default_local_bootstrap_model=default_local_bootstrap_model,
        default_local_bootstrap_display_name=default_local_bootstrap_display_name,
        default_local_bootstrap_profile=default_local_bootstrap_profile,
        default_ollama_base_url_func=default_ollama_base_url_func,
    )


def _provider_health_payload(provider: LLMProvider, available_models: list) -> dict[str, Any]:
    readiness = resolve_provider_readiness(provider)
    return {
        "provider_id": provider.id,
        "health_status": provider.health_status or "",
        "readiness_status": readiness["status"],
        "readiness_reason": readiness["reason"],
        "readiness": readiness,
        "last_health_check_at": provider.last_health_check_at.isoformat() if provider.last_health_check_at else "",
        "last_health_error": provider.last_health_error or "",
        "available_models": available_models,
        "endpoint_url": provider.endpoint_url or "",
        "binary_path": provider.binary_path or "",
        "config_json": provider.config_json if isinstance(provider.config_json, dict) else {},
        "capabilities_json": provider.capabilities_json if isinstance(provider.capabilities_json, dict) else {},
    }


async def refresh_provider_health(
    db: AsyncSession,
    *,
    provider_id: str,
    infer_provider_runtime_func,
    ensure_provider_local_runtime_ready_func,
    probe_ollama_endpoint_func,
    default_ollama_base_url_func,
    apply_provider_runtime_defaults_func,
    utc_now_func,
) -> dict[str, Any]:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    runtime = infer_provider_runtime_func(
        name=provider.name,
        driver=provider.driver,
        provider_family=provider.provider_family,
        runtime_kind=provider.runtime_kind,
        auth_mode=provider.auth_mode,
    )
    if runtime["driver"] == "ollama":
        await ensure_provider_local_runtime_ready_func(provider)
        probe = await probe_ollama_endpoint_func(provider.endpoint_url or default_ollama_base_url_func())
        provider.endpoint_url = probe["base_url"]
        provider.health_status = probe["status"]
        provider.last_health_check_at = utc_now_func()
        provider.last_health_error = probe["error"] or None
        config_json, capabilities_json = apply_provider_runtime_defaults_func(
            provider,
            runtime=runtime,
            config_json=provider.config_json if isinstance(provider.config_json, dict) else {},
            capabilities_json=provider.capabilities_json if isinstance(provider.capabilities_json, dict) else {},
        )
        capabilities_json.update(
            {
                "available_models": probe["model_ids"],
                "supports_health_check": True,
            }
        )
        provider.config_json = config_json or None
        provider.capabilities_json = capabilities_json or None
        available_models = probe["model_ids"]
    else:
        raise HTTPException(
            status_code=400,
            detail="Native health checks are currently supported only for Ollama providers",
        )
    await db.commit()
    await db.refresh(provider)
    return _provider_health_payload(provider, available_models)


async def pull_provider_model(
    db: AsyncSession,
    *,
    provider_id: str,
    model_id: str,
    infer_provider_runtime_func,
    pull_ollama_model_func,
    default_ollama_base_url_func,
    refresh_provider_health_func,
) -> dict[str, Any]:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    runtime = infer_provider_runtime_func(
        name=provider.name,
        driver=provider.driver,
        provider_family=provider.provider_family,
        runtime_kind=provider.runtime_kind,
        auth_mode=provider.auth_mode,
    )
    if runtime["driver"] != "ollama":
        raise HTTPException(
            status_code=400,
            detail="Model pulls are currently supported only for Ollama providers",
        )
    pull_result = await pull_ollama_model_func(
        provider.endpoint_url or default_ollama_base_url_func(),
        model_id=model_id,
    )
    health = await refresh_provider_health_func(db, provider_id=provider.id)
    return {
        "status": "ok",
        "provider_id": provider.id,
        "model_id": model_id,
        "pull": pull_result,
        "health": health,
    }


__all__ = ["get_local_bootstrap_status", "pull_provider_model", "refresh_provider_health"]
