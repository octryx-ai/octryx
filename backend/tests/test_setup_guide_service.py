"""The setup guide requires a local anchor by default, marks core steps complete with a primary anchor and counts the active providers."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.control_plane_service import get_or_create_control_plane_config
from app.services.local_bootstrap import ensure_local_bootstrap
from app.services.setup_guide import get_setup_guide_status
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_setup_guide_requires_local_anchor_by_default(db):
    status = await get_setup_guide_status(db)

    # Runtime setup order: provider ready → models → default → (gateway) → Workspaces.
    keys = [step["key"] for step in status["steps"]]
    assert keys[0] == "provider" and keys[-1] == "workspaces"
    assert {"models", "default"} <= set(keys)
    if status["steps"][0]["status"] == "pending":
        assert status["ready"] is False and "local_anchor" in keys


@pytest.mark.asyncio
async def test_setup_guide_marks_core_steps_complete_when_local_anchor_is_primary(db, monkeypatch):
    async def fake_start_runtime(*, driver: str, endpoint_url: str, **_kwargs):
        assert driver == "ollama"
        assert endpoint_url == "http://ollama:11434"
        return {"status": "ready", "started": True}

    async def fake_probe(_base_url: str, *, timeout_seconds: float = 20.0):
        assert timeout_seconds == 20.0
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

    await ensure_local_bootstrap(
        db,
        endpoint_url="http://ollama:11434",
        model_id="gemma4",
        pull_model=False,
        make_primary=True,
    )

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    # The local model can run and is #1, but nobody cleared it for data yet: the guide names exactly that.
    assert by_key["provider"]["status"] == "completed"
    assert "local_anchor" not in by_key
    assert by_key["default"]["status"] == "pending" and "not cleared for data" in by_key["default"]["detail"]
    assert status["ready"] is False


async def _seed_local_and_api_providers(db) -> tuple[LLMProvider, LLMProvider]:
    local_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        display_name="Local Gemma 4 Anchor",
        endpoint_url="http://ollama:11434",
        auth_mode="none",
        default_model_id="gemma4",
        bootstrap_role="default_anchor",
        health_status="ok",
        last_health_check_at=utc_now(),
        is_global=True,
        is_active=True,
    )
    api_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        provider_family="openrouter",
        driver="openrouter_api",
        runtime_kind="api",
        display_name="Hosted API",
        auth_mode="api_key",
        # Readiness needs a stored key reference; the value is never resolved here.
        api_key_secret_ref=str(uuid.uuid4()),
        is_global=True,
        is_active=True,
    )
    db.add_all([local_provider, api_provider])
    await db.flush()
    return local_provider, api_provider


async def _seed_model_runtime_targets_and_default(db, config, local_provider: LLMProvider, api_provider: LLMProvider):
    db.add(
        LLMModel(
            id=str(uuid.uuid4()),
            provider_id=local_provider.id,
            model_id="gemma4",
            display_name="gemma4",
            supports_tools=True,
            supports_streaming=True,
            is_active=True,
            last_synced_at=utc_now(),
        )
    )
    # Insert the model before the targets: a target's insert listener adds a catalog row when none exists yet.
    await db.flush()

    db.add_all(
        [
            ControlPlaneRuntimeTarget(
                id=str(uuid.uuid4()),
                config_id=config.id,
                provider_id=local_provider.id,
                model_id="gemma4",
                priority=1,
                is_active=True,
            ),
            ControlPlaneRuntimeTarget(
                id=str(uuid.uuid4()),
                config_id=config.id,
                provider_id=api_provider.id,
                model_id="openrouter/auto",
                priority=2,
                is_active=True,
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_setup_guide_counts_active_providers(db):
    config = await get_or_create_control_plane_config(db)
    # The test baseline already holds the fallback API provider.
    baseline_api = (await db.execute(select(func.count(LLMProvider.id)).where(
        LLMProvider.is_active, LLMProvider.runtime_kind == "api"))).scalar_one()

    local_provider, api_provider = await _seed_local_and_api_providers(db)
    await _seed_model_runtime_targets_and_default(db, config, local_provider, api_provider)

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    assert status["stats"]["api_provider_count"] == baseline_api + 1
    assert status["stats"]["local_provider_count"] == 1
    total_active = (await db.execute(select(func.count(LLMProvider.id)).where(LLMProvider.is_active))).scalar_one()
    assert status["stats"]["active_provider_count"] == total_active
    assert status["stats"]["active_runtime_count"] >= 2
    assert by_key["provider"]["status"] == "completed" and "Hosted API" in by_key["provider"]["detail"]
    assert "legacy_providers" not in by_key
    assert "cli_profiles" not in by_key
