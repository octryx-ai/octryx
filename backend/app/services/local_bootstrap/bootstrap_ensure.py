"""Bootstrapping the managed local Ollama anchor: endpoint, model, provider, model row and runtime target."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from .bootstrap_state import serialize_bootstrap_state


async def _reachable_model(
    *,
    normalized_endpoint: str,
    requested_model_id: str,
    pull_model: bool,
    ensure_local_runtime_started_func,
    probe_ollama_endpoint_func,
    resolve_ollama_model_id_func,
    pull_ollama_model_func,
) -> tuple[dict[str, Any], str, str]:
    """Start and probe the runtime (pulling the model when asked); returns the probe, endpoint and model id."""
    await ensure_local_runtime_started_func(driver="ollama", endpoint_url=normalized_endpoint)
    probe = await probe_ollama_endpoint_func(normalized_endpoint)
    if not probe["ok"]:
        raise HTTPException(status_code=400, detail=f"Ollama endpoint is not reachable: {probe['error']}")
    resolved_endpoint = str(probe.get("base_url") or normalized_endpoint).strip() or normalized_endpoint

    resolved_model_id = resolve_ollama_model_id_func(requested_model_id, probe["model_ids"])
    if pull_model and not resolved_model_id:
        await pull_ollama_model_func(resolved_endpoint, model_id=requested_model_id)
        probe = await probe_ollama_endpoint_func(resolved_endpoint)
        if not probe["ok"]:
            raise HTTPException(status_code=400, detail=f"Ollama became unavailable after pull: {probe['error']}")
        resolved_endpoint = str(probe.get("base_url") or resolved_endpoint).strip() or resolved_endpoint
        resolved_model_id = resolve_ollama_model_id_func(requested_model_id, probe["model_ids"])

    if not resolved_model_id:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{requested_model_id}' is not available in Ollama. Pull it first or enable automatic pull.",
        )
    return probe, resolved_endpoint, resolved_model_id


async def _anchor_provider(db: AsyncSession, *, resolved_endpoint: str) -> LLMProvider:
    """The default anchor, else the global Ollama provider at this endpoint, else a new one."""
    provider = (
        (
            await db.execute(
                select(LLMProvider)
                .where(
                    LLMProvider.driver == "ollama",
                    LLMProvider.is_global,
                    LLMProvider.bootstrap_role == "default_anchor",
                )
                .order_by(LLMProvider.updated_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if not provider:
        provider = (
            (
                await db.execute(
                    select(LLMProvider)
                    .where(
                        LLMProvider.driver == "ollama",
                        LLMProvider.is_global,
                        LLMProvider.endpoint_url == resolved_endpoint,
                    )
                    .order_by(LLMProvider.updated_at.desc())
                )
            )
            .scalars()
            .first()
        )

    if not provider:
        provider = LLMProvider(
            id=str(uuid.uuid4()),
            name="ollama",
            provider_family="local",
            driver="ollama",
            runtime_kind="local",
            is_global=True,
            is_active=True,
        )
        db.add(provider)
    return provider


def _configure_anchor_provider(
    provider: LLMProvider,
    *,
    display_name: str,
    probe: dict[str, Any],
    resolved_endpoint: str,
    resolved_model_id: str,
    requested_model_id: str,
    default_local_bootstrap_display_name: str,
    default_local_bootstrap_profile: str,
    apply_provider_runtime_defaults_func,
    utc_now_func,
) -> None:
    provider.display_name = str(display_name or "").strip() or default_local_bootstrap_display_name
    provider.profile_name = default_local_bootstrap_profile
    provider.endpoint_url = resolved_endpoint
    provider.auth_mode = "none"
    provider.bootstrap_role = "default_anchor"
    provider.default_model_id = resolved_model_id
    provider.health_status = probe["status"]
    provider.last_health_check_at = utc_now_func()
    provider.last_health_error = probe["error"] or None
    provider.capabilities_json = {
        **(provider.capabilities_json if isinstance(provider.capabilities_json, dict) else {}),
        "managed_local": True,
        "supports_model_pull": True,
        "supports_health_check": True,
    }
    provider.config_json = {
        **(dict(provider.config_json) if isinstance(provider.config_json, dict) else {}),
        "managed_local": True,
        "bootstrap_model": resolved_model_id,
        "requested_bootstrap_model": requested_model_id,
        "profile_home": f"/app/data/provider_profiles/{provider.id}/home",
    }
    config_json, capabilities_json = apply_provider_runtime_defaults_func(
        provider,
        runtime={
            "driver": "ollama",
            "runtime_kind": "local",
            "provider_family": "local",
            "name": "ollama",
            "auth_mode": "none",
        },
        config_json=provider.config_json,
        capabilities_json=provider.capabilities_json,
    )
    provider.config_json = config_json or None
    provider.capabilities_json = capabilities_json or None


async def _anchor_model(
    db: AsyncSession, *, provider: LLMProvider, probe: dict[str, Any], resolved_model_id: str, utc_now_func
) -> LLMModel:
    probe_model = next((item for item in probe["models"] if item["id"] == resolved_model_id), None)
    model = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.model_id == resolved_model_id,
            )
        )
    ).scalar_one_or_none()
    if not model:
        model = LLMModel(
            id=str(uuid.uuid4()),
            provider_id=provider.id,
            model_id=resolved_model_id,
        )
        db.add(model)
    model.display_name = resolved_model_id
    model.supports_tools = True
    model.supports_streaming = True
    model.is_active = True
    model.last_synced_at = utc_now_func()
    if model.max_tokens_per_request is None:
        provider_config = provider.config_json if isinstance(provider.config_json, dict) else {}
        model.max_tokens_per_request = int(provider_config.get("default_max_tokens_per_request") or 512)
    if probe_model and probe_model.get("context_length"):
        model.context_length = int(probe_model["context_length"])
    return model


async def _finish_bootstrap(
    db: AsyncSession,
    *,
    provider: LLMProvider,
    model: LLMModel,
    probe: dict[str, Any],
    resolved_model_id: str,
    make_primary: bool,
    upsert_runtime_target_func,
    get_or_create_control_plane_config_func,
    get_runtime_targets_func,
    serialize_options: dict[str, Any],
) -> dict[str, Any]:
    """Register the runtime target and the default model, commit, and describe the result."""
    runtime_target = await upsert_runtime_target_func(
        db,
        provider=provider,
        model_id=resolved_model_id,
        make_primary=make_primary,
        is_active=True,
    )
    if not make_primary:
        config = await get_or_create_control_plane_config_func(db)
        targets = await get_runtime_targets_func(db, config)
        if len(targets) == 1 and targets[0].id == runtime_target.id:
            runtime_target.priority = 1

    await db.commit()
    await db.refresh(provider)
    await db.refresh(runtime_target)
    await db.refresh(model)

    return serialize_bootstrap_state(
        provider=provider,
        runtime_target=runtime_target,
        installed_model=model,
        available_models=probe["model_ids"],
        **serialize_options,
    )


async def ensure_local_bootstrap(
    db: AsyncSession,
    *,
    endpoint_url: str | None,
    model_id: str,
    display_name: str,
    pull_model: bool,
    make_primary: bool,
    default_local_bootstrap_model: str,
    default_local_bootstrap_display_name: str,
    default_local_bootstrap_profile: str,
    normalize_ollama_base_url_func,
    ensure_local_runtime_started_func,
    probe_ollama_endpoint_func,
    resolve_ollama_model_id_func,
    pull_ollama_model_func,
    apply_provider_runtime_defaults_func,
    upsert_runtime_target_func,
    get_or_create_control_plane_config_func,
    get_runtime_targets_func,
    utc_now_func,
    default_ollama_base_url_func,
) -> dict[str, Any]:
    normalized_endpoint = normalize_ollama_base_url_func(endpoint_url)
    requested_model_id = str(model_id or "").strip() or default_local_bootstrap_model
    probe, resolved_endpoint, resolved_model_id = await _reachable_model(
        normalized_endpoint=normalized_endpoint, requested_model_id=requested_model_id, pull_model=pull_model,
        ensure_local_runtime_started_func=ensure_local_runtime_started_func,
        probe_ollama_endpoint_func=probe_ollama_endpoint_func,
        resolve_ollama_model_id_func=resolve_ollama_model_id_func, pull_ollama_model_func=pull_ollama_model_func,
    )
    provider = await _anchor_provider(db, resolved_endpoint=resolved_endpoint)
    _configure_anchor_provider(
        provider, display_name=display_name, probe=probe, resolved_endpoint=resolved_endpoint,
        resolved_model_id=resolved_model_id, requested_model_id=requested_model_id,
        default_local_bootstrap_display_name=default_local_bootstrap_display_name,
        default_local_bootstrap_profile=default_local_bootstrap_profile,
        apply_provider_runtime_defaults_func=apply_provider_runtime_defaults_func, utc_now_func=utc_now_func,
    )
    await db.flush()
    model = await _anchor_model(
        db, provider=provider, probe=probe, resolved_model_id=resolved_model_id, utc_now_func=utc_now_func
    )
    return await _finish_bootstrap(
        db, provider=provider, model=model, probe=probe, resolved_model_id=resolved_model_id,
        make_primary=make_primary, upsert_runtime_target_func=upsert_runtime_target_func,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config_func,
        get_runtime_targets_func=get_runtime_targets_func,
        serialize_options={
            "default_local_bootstrap_model": default_local_bootstrap_model,
            "default_local_bootstrap_display_name": default_local_bootstrap_display_name,
            "default_local_bootstrap_profile": default_local_bootstrap_profile,
            "default_ollama_base_url_func": default_ollama_base_url_func,
        },
    )
