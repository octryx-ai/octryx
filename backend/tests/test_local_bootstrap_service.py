"""Local bootstrap creates the provider, model and primary runtime, pulls a missing model, resolves the gemma4 alias and prefers the database control-plane model in its status."""

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.local_bootstrap import ensure_local_bootstrap, get_local_bootstrap_status
from app.services.system_config import get_agent_default_model


@pytest.mark.asyncio
async def test_ensure_local_bootstrap_creates_provider_model_and_primary_runtime(db, monkeypatch):
    start_calls: list[str] = []

    async def fake_start_runtime(*, driver: str, endpoint_url: str, **_kwargs):
        start_calls.append(f"{driver}:{endpoint_url}")
        return {"status": "ready", "started": True}

    async def fake_probe(base_url: str, *, timeout_seconds: float = 20.0):
        assert base_url == "http://ollama:11434"
        return {
            "ok": True,
            "status": "ok",
            "base_url": "http://ollama:11434",
            "models": [{"id": "gemma4", "context_length": 131072}],
            "model_ids": ["gemma4"],
            "error": "",
        }

    monkeypatch.setattr("app.services.local_bootstrap.service.ensure_local_runtime_started", fake_start_runtime)
    monkeypatch.setattr("app.services.local_bootstrap.service.probe_ollama_endpoint", fake_probe)

    result = await ensure_local_bootstrap(
        db,
        endpoint_url="http://ollama:11434",
        model_id="gemma4",
        pull_model=False,
        make_primary=True,
    )

    assert result["setup_complete"] is True
    assert result["installed"] is True
    assert result["is_primary"] is True
    assert result["model_id"] == "gemma4"
    assert start_calls == ["ollama:http://ollama:11434"]

    provider = (
        await db.execute(
            select(LLMProvider).where(
                LLMProvider.driver == "ollama",
                LLMProvider.bootstrap_role == "default_anchor",
            )
        )
    ).scalar_one()
    assert provider.display_name == "Local Gemma 4 Anchor"
    assert provider.default_model_id == "gemma4"
    assert provider.health_status == "ok"
    assert provider.config_json["request_timeout_seconds"] == 180
    assert provider.config_json["default_max_tokens_per_request"] == 512
    model = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.model_id == "gemma4",
            )
        )
    ).scalar_one()
    assert model.is_active is True
    assert model.context_length == 131072
    assert model.max_tokens_per_request == 512

    runtime_target = (
        await db.execute(
            select(ControlPlaneRuntimeTarget).where(
                ControlPlaneRuntimeTarget.provider_id == provider.id,
                ControlPlaneRuntimeTarget.model_id == "gemma4",
            )
        )
    ).scalar_one()
    assert runtime_target.priority == 1
    assert runtime_target.is_active is True

    assert await get_agent_default_model(db) == "gemma4"


@pytest.mark.asyncio
async def test_ensure_local_bootstrap_pulls_missing_model_when_requested(db, monkeypatch):
    probe_calls = {"count": 0}
    pull_calls: list[str] = []

    async def fake_probe(_base_url: str, *, timeout_seconds: float = 20.0):
        probe_calls["count"] += 1
        if probe_calls["count"] == 1:
            return {
                "ok": True,
                "status": "ok",
                "base_url": "http://ollama:11434",
                "models": [],
                "model_ids": [],
                "error": "",
            }
        return {
            "ok": True,
            "status": "ok",
            "base_url": "http://ollama:11434",
            "models": [{"id": "gemma4", "context_length": None}],
            "model_ids": ["gemma4"],
            "error": "",
        }

    async def fake_pull(_base_url: str, *, model_id: str, timeout_seconds: float = 1800.0):
        pull_calls.append(model_id)
        return {"ok": True, "status": "ok", "model_id": model_id}

    async def fake_start_runtime(*, driver: str, endpoint_url: str, **_kwargs):
        return {"status": "ready", "started": False}

    monkeypatch.setattr("app.services.local_bootstrap.service.ensure_local_runtime_started", fake_start_runtime)
    monkeypatch.setattr("app.services.local_bootstrap.service.probe_ollama_endpoint", fake_probe)
    monkeypatch.setattr("app.services.local_bootstrap.service.pull_ollama_model", fake_pull)

    result = await ensure_local_bootstrap(db, endpoint_url="http://ollama:11434", model_id="gemma4")

    assert result["setup_complete"] is True
    assert pull_calls == ["gemma4"]


@pytest.mark.asyncio
async def test_ensure_local_bootstrap_resolves_gemma4_alias_to_installed_variant(db, monkeypatch):
    async def fake_probe(_base_url: str, *, timeout_seconds: float = 20.0):
        return {
            "ok": True,
            "status": "ok",
            "base_url": "http://localhost:11434",
            "models": [{"id": "gemma4:e4b", "context_length": 131072}],
            "model_ids": ["gemma4:e4b"],
            "error": "",
        }

    async def fake_start_runtime(*, driver: str, endpoint_url: str, **_kwargs):
        return {"status": "ready", "started": False}

    monkeypatch.setattr("app.services.local_bootstrap.service.ensure_local_runtime_started", fake_start_runtime)
    monkeypatch.setattr("app.services.local_bootstrap.service.probe_ollama_endpoint", fake_probe)

    result = await ensure_local_bootstrap(
        db,
        endpoint_url="http://ollama:11434",
        model_id="gemma4",
        pull_model=False,
        make_primary=True,
    )

    assert result["model_id"] == "gemma4:e4b"
    assert result["endpoint_url"] == "http://localhost:11434"

    provider = (
        await db.execute(
            select(LLMProvider).where(
                LLMProvider.driver == "ollama",
                LLMProvider.bootstrap_role == "default_anchor",
            )
        )
    ).scalar_one()
    assert provider.default_model_id == "gemma4:e4b"


@pytest.mark.asyncio
async def test_local_bootstrap_status_prefers_db_control_plane_model_over_provider_default(db):
    # Every ordered model has a Model catalog row now; remove them with their providers.
    for model in (await db.execute(select(LLMModel))).scalars().all():
        await db.delete(model)
    providers = (await db.execute(select(LLMProvider))).scalars().all()
    for provider in providers:
        await db.delete(provider)
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    control_plane_configs = (await db.execute(select(ControlPlaneConfig))).scalars().all()
    for config in control_plane_configs:
        await db.delete(config)
    await db.flush()

    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        display_name="Local Runtime",
        endpoint_url="http://ollama:11434",
        default_model_id="provider-model",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()

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

    status = await get_local_bootstrap_status(db)

    assert status["model_id"] == "db-model"
    assert status["recommended_model_id"] == "db-model"
