"""Provider health refresh updates the Ollama provider and reports unavailable readiness for a failed probe, and model id resolution prefers the installed gemma4 variant."""

import uuid

import pytest

from app.models import LLMProvider
from app.services.local_bootstrap import (
    canonicalize_ollama_pull_model,
    refresh_provider_health,
    resolve_ollama_model_id,
)


@pytest.mark.asyncio
async def test_refresh_provider_health_updates_ollama_provider(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        display_name="Local Runtime",
        endpoint_url="http://ollama:11434",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_probe(_base_url: str, *, timeout_seconds: float = 20.0):
        return {
            "ok": True,
            "status": "ok",
            "base_url": "http://ollama:11434",
            "models": [{"id": "gemma4", "context_length": None}],
            "model_ids": ["gemma4"],
            "error": "",
        }

    async def fake_ensure_runtime_ready(_provider):
        return {"status": "ready", "started": False}

    monkeypatch.setattr(
        "app.services.local_bootstrap.service.ensure_provider_local_runtime_ready",
        fake_ensure_runtime_ready,
    )
    monkeypatch.setattr("app.services.local_bootstrap.service.probe_ollama_endpoint", fake_probe)

    result = await refresh_provider_health(db, provider_id=provider.id)

    assert result["health_status"] == "ok"
    assert result["readiness_status"] == "ready"
    assert result["readiness_reason"] == "health_check_ok"
    assert "gemma4" in result["available_models"]

    refreshed = await db.get(LLMProvider, provider.id)
    assert refreshed is not None
    assert refreshed.health_status == "ok"
    assert refreshed.last_health_check_at is not None


@pytest.mark.asyncio
async def test_refresh_provider_health_reports_unavailable_readiness_for_failed_probe(db, monkeypatch):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        display_name="Local Runtime",
        endpoint_url="http://ollama:11434",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    async def fake_probe(_base_url: str, *, timeout_seconds: float = 20.0):
        return {
            "ok": False,
            "status": "error",
            "base_url": "http://ollama:11434",
            "models": [],
            "model_ids": [],
            "error": "connection refused",
        }

    async def fake_ensure_runtime_ready(_provider):
        return {"status": "ready", "started": False}

    monkeypatch.setattr(
        "app.services.local_bootstrap.service.ensure_provider_local_runtime_ready",
        fake_ensure_runtime_ready,
    )
    monkeypatch.setattr("app.services.local_bootstrap.service.probe_ollama_endpoint", fake_probe)

    result = await refresh_provider_health(db, provider_id=provider.id)

    assert result["health_status"] == "error"
    assert result["readiness_status"] == "unavailable"
    assert result["readiness_reason"] == "health_error"
    assert result["readiness"]["runtime_attempt_allowed"] is False
    assert result["last_health_error"] == "connection refused"


def test_resolve_ollama_model_id_prefers_installed_gemma4_variant():
    assert resolve_ollama_model_id("gemma4", ["gemma4:e2b", "gemma4:e4b"]) == "gemma4:e4b"
    assert canonicalize_ollama_pull_model("gemma4") == "gemma4:e4b"
