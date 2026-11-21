"""DB-backed default models across control plane defaults, runtime targets, admin helpers and the context."""

import uuid

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from app.services.admin.provider.admin_control_plane_service import save_control_plane_provider
from app.services.control_plane.config import (
    resolve_control_plane_default_model,
    resolve_control_plane_promoted_model,
)
from app.services.control_plane_service import (
    ensure_default_runtime_target,
    get_or_create_control_plane_config,
)
from app.web._helpers.control_plane import _build_control_plane_context


@pytest.mark.asyncio
async def test_a_new_control_plane_config_without_runtime_targets_names_no_model(db):
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    configs = (await db.execute(select(ControlPlaneConfig))).scalars().all()
    for config in configs:
        await db.delete(config)
    await db.commit()

    config = await get_or_create_control_plane_config(db)

    assert not config.model_id


@pytest.mark.asyncio
async def test_control_plane_default_runtime_target_prefers_db_config_model(db):
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    configs = (await db.execute(select(ControlPlaneConfig))).scalars().all()
    for config in configs:
        await db.delete(config)
    await db.flush()

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Default Provider",
        default_model_id="provider-model",
        is_global=True,
        is_active=True,
    )
    config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name="default",
        provider_id=provider.id,
        model_id="db-model",
        is_active=True,
    )
    db.add(provider)
    db.add(config)
    await db.commit()

    await ensure_default_runtime_target(db, config)
    await db.commit()

    target = (
        await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.config_id == config.id))
    ).scalar_one()
    assert target.model_id == "db-model"


async def _delete_runtime_targets_and_configs(db) -> None:
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    configs = (await db.execute(select(ControlPlaneConfig))).scalars().all()
    for config in configs:
        await db.delete(config)
    await db.flush()


def _assert_default_and_promoted_models(provider: LLMProvider, config: ControlPlaneConfig) -> None:
    assert (
        resolve_control_plane_default_model(
            provider,
            config=config,
            fallback_model_id="fallback-model",
        )
        == "db-model"
    )
    assert (
        resolve_control_plane_promoted_model(
            provider,
            config=config,
            fallback_model_id="fallback-model",
        )
        == "provider-model"
    )


async def _sync_primary_runtime_target(_db, _config):
    raise AssertionError("sync_primary_runtime_target should not run when set_as_active is true")


def _provider_secret_scope_func(_provider):
    return ("provider", "api_key")


async def _set_secret_value_func(*_args, **_kwargs):
    raise AssertionError("set_secret_value_func should not be called for blank api_key")


async def _build_provider_client_kwargs_async_func(*_args, **_kwargs):
    raise AssertionError("build_provider_client_kwargs_async_func should not be called")


def _get_provider_func(*_args, **_kwargs):
    raise AssertionError("get_provider_func should not be called")


async def _save_provider_as_active(db, provider: LLMProvider, *, ensure_defaults, upsert_runtime_target) -> str:
    return await save_control_plane_provider(
        db,
        provider_id="",
        driver=provider.driver,
        display_name=provider.display_name or "",
        auth_mode="api_key",
        api_key="",
        aws_region="",
        aws_role_arn="",
        is_active=True,
        set_as_active=True,
        model_id="provider-model",
        sync_models=False,
        ensure_control_plane_defaults_func=ensure_defaults,
        upsert_runtime_target_func=upsert_runtime_target,
        sync_primary_runtime_target_func=_sync_primary_runtime_target,
        provider_secret_scope_func=_provider_secret_scope_func,
        set_secret_value_func=_set_secret_value_func,
        build_provider_client_kwargs_async_func=_build_provider_client_kwargs_async_func,
        get_provider_func=_get_provider_func,
        default_model_id="fallback-model",
    )


@pytest.mark.asyncio
async def test_control_plane_default_model_resolution_stays_explicit_across_admin_and_runtime_helpers(db):
    await _delete_runtime_targets_and_configs(db)

    config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name="default",
        model_id="db-model",
        is_active=True,
    )
    db.add(config)
    await db.flush()

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Explicit Provider",
        default_model_id="provider-model",
        is_global=True,
        is_active=True,
    )

    _assert_default_and_promoted_models(provider, config)

    captured: dict[str, object] = {}

    async def ensure_defaults(_db):
        return config

    async def upsert_runtime_target(
        _db,
        *,
        provider,
        model_id,
        make_primary,
        is_active,
    ):
        captured.update(
            provider_id=provider.id,
            model_id=model_id,
            make_primary=make_primary,
            is_active=is_active,
        )

    updated_provider_id = await _save_provider_as_active(
        db, provider, ensure_defaults=ensure_defaults, upsert_runtime_target=upsert_runtime_target
    )

    saved_provider = await db.get(LLMProvider, updated_provider_id)
    assert saved_provider is not None
    assert saved_provider.default_model_id == "provider-model"
    assert captured["model_id"] == "provider-model"
    assert captured["make_primary"] is True
    assert captured["is_active"] is True


@pytest.mark.asyncio
async def test_control_plane_context_prefers_db_model_for_selected_model(db):
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    configs = (await db.execute(select(ControlPlaneConfig))).scalars().all()
    for config in configs:
        await db.delete(config)
    await db.flush()

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Provider",
        default_model_id="provider-model",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    db.add(
        ControlPlaneConfig(
            id=str(uuid.uuid4()),
            name="default",
            provider_id=provider.id,
            model_id="db-model",
            is_active=True,
        )
    )
    await db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/control-plane",
            "headers": [],
            "query_string": b"",
        }
    )
    context = await _build_control_plane_context(request, db, edit_provider_id=provider.id)

    assert context["selected_model_id"] == "db-model"
