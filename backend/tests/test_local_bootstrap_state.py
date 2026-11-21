from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.local_bootstrap.bootstrap_state import serialize_bootstrap_state


def test_serialize_bootstrap_state_prefers_installed_model_and_provider_fields():
    provider = SimpleNamespace(
        id="provider-1",
        display_name="Local Anchor",
        endpoint_url="http://ollama:11434",
        profile_name="bootstrap",
        default_model_id="provider-model",
        bootstrap_role="default_anchor",
        health_status="ok",
        last_health_check_at=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
        last_health_error="",
    )
    runtime_target = SimpleNamespace(id="target-1", priority=1, is_active=True)
    installed_model = SimpleNamespace(model_id="installed-model", is_active=True)

    state = serialize_bootstrap_state(
        provider=provider,
        runtime_target=runtime_target,
        installed_model=installed_model,
        resolved_model_id="resolved-model",
        available_models=["installed-model"],
        default_local_bootstrap_model="fallback-model",
        default_local_bootstrap_display_name="Fallback Display",
        default_local_bootstrap_profile="fallback-profile",
        default_ollama_base_url_func=lambda: "http://localhost:11434",
    )

    assert state["provider_id"] == "provider-1"
    assert state["provider_display_name"] == "Local Anchor"
    assert state["endpoint_url"] == "http://ollama:11434"
    assert state["profile_name"] == "bootstrap"
    assert state["model_id"] == "installed-model"
    assert state["runtime_target_id"] == "target-1"
    assert state["runtime_priority"] == 1
    assert state["is_primary"] is True
    assert state["installed"] is True
    assert state["setup_complete"] is True
    assert state["managed_by_system"] is True
    assert state["recommended_model_id"] == "installed-model"
    assert state["last_health_check_at"] == "2026-04-20T10:30:00+00:00"


def test_serialize_bootstrap_state_falls_back_to_defaults_without_provider():
    state = serialize_bootstrap_state(
        provider=None,
        runtime_target=None,
        installed_model=None,
        default_local_bootstrap_model="fallback-model",
        default_local_bootstrap_display_name="Fallback Display",
        default_local_bootstrap_profile="fallback-profile",
        default_ollama_base_url_func=lambda: "http://localhost:11434",
    )

    assert state["provider_id"] == ""
    assert state["provider_display_name"] == "Fallback Display"
    assert state["endpoint_url"] == "http://localhost:11434"
    assert state["profile_name"] == "fallback-profile"
    assert state["model_id"] == "fallback-model"
    assert state["installed"] is False
    assert state["setup_complete"] is False
    assert state["available_models"] == []
    assert state["recommended_model_id"] == "fallback-model"
