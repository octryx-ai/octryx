"""Created providers store runtime metadata, client kwargs expose the driver metadata and start a local runtime, and control plane runtimes get the Ollama timeout and token defaults."""

import uuid

import pytest

from app.models import LLMProvider
from app.services.admin.provider.admin_provider_service import create_provider
from app.services.control_plane_service import build_provider_client_kwargs_async, resolve_control_plane_runtimes


@pytest.mark.asyncio
async def test_create_provider_stores_runtime_metadata(db):
    provider_row: LLMProvider | None = None

    def _serialize(provider, model_count, active_count):
        nonlocal provider_row
        provider_row = provider
        return {
            "id": provider.id,
            "driver": provider.driver,
            "runtime_kind": provider.runtime_kind,
            "profile_name": provider.profile_name,
            "endpoint_url": provider.endpoint_url,
            "bootstrap_role": provider.bootstrap_role,
        }

    created = await create_provider(
        db,
        payload={
            "driver": "ollama",
            "display_name": "Local Gemma Bootstrap",
            "profile_name": "bootstrap",
            "endpoint_url": "http://ollama:11434",
            "bootstrap_role": "default_anchor",
            "config_json": {"profile_home": "/app/data/provider_profiles/bootstrap"},
            "is_global": True,
        },
        serialize_provider=_serialize,
    )

    assert created["driver"] == "ollama"
    assert created["runtime_kind"] == "local"
    assert created["profile_name"] == "bootstrap"
    assert created["endpoint_url"] == "http://ollama:11434"
    assert created["bootstrap_role"] == "default_anchor"
    assert provider_row is not None
    assert provider_row.config_json["request_timeout_seconds"] == 180
    assert provider_row.config_json["default_max_tokens_per_request"] == 512
    assert "think" not in provider_row.config_json


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_exposes_driver_metadata(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        profile_name="bootstrap",
        endpoint_url="http://ollama:11434",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_ensure_runtime_ready(_provider):
        return {"status": "ready", "started": False}

    monkeypatch.setattr(
        "app.services.control_plane_service.ensure_provider_local_runtime_ready",
        fake_ensure_runtime_ready,
    )

    kwargs = await build_provider_client_kwargs_async(db, provider)

    assert kwargs["provider_name"] == "ollama"
    assert kwargs["driver"] == "ollama"
    assert kwargs["provider_family"] == "local"
    assert kwargs["runtime_kind"] == "local"
    assert kwargs["profile_name"] == "bootstrap"
    assert kwargs["endpoint_url"] == "http://ollama:11434"
    assert kwargs["auth_mode"] == "none"


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_starts_local_runtime(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        profile_name="bootstrap",
        endpoint_url="http://localhost:11434",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_ensure_runtime_ready(_provider):
        return {"status": "ready", "started": True}

    monkeypatch.setattr(
        "app.services.control_plane_service.ensure_provider_local_runtime_ready",
        fake_ensure_runtime_ready,
    )

    kwargs = await build_provider_client_kwargs_async(db, provider)

    assert kwargs["endpoint_url"] == "http://localhost:11434"
    assert kwargs["auth_mode"] == "none"


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_applies_ollama_timeout_and_token_defaults(db, monkeypatch):
    from app.services.control_plane_service import get_or_create_control_plane_config

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        profile_name="bootstrap",
        endpoint_url="http://localhost:11434",
        auth_mode="none",
        config_json={"request_timeout_seconds": 180, "default_max_tokens_per_request": 512},
        default_model_id="gemma4:e4b",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()

    from app.models import ControlPlaneRuntimeTarget, LLMModel

    config = await get_or_create_control_plane_config(db)
    config.model_id = "gemma4:e4b"
    config.provider_id = provider.id
    config.is_active = True
    db.add(
        LLMModel(
            id=str(uuid.uuid4()),
            provider_id=provider.id,
            model_id="gemma4:e4b",
            display_name="gemma4:e4b",
            supports_tools=True,
            supports_streaming=True,
            is_active=True,
        )
    )
    db.add(
        ControlPlaneRuntimeTarget(
            id=str(uuid.uuid4()),
            config_id=config.id,
            provider_id=provider.id,
            model_id="gemma4:e4b",
            priority=1,
            is_active=True,
        )
    )
    await db.commit()

    async def fake_ensure_runtime_ready(_provider):
        return {"status": "ready", "started": False}

    monkeypatch.setattr(
        "app.services.control_plane_service.ensure_provider_local_runtime_ready",
        fake_ensure_runtime_ready,
    )

    runtimes = await resolve_control_plane_runtimes(db)
    ollama_runtime = next(runtime for runtime in runtimes if runtime["provider_id"] == provider.id)

    assert ollama_runtime["request_timeout_seconds"] == 180
    assert ollama_runtime["max_tokens_per_request"] == 512
    assert ollama_runtime["supports_tools"] is True
    assert ollama_runtime["supports_vision"] is False
