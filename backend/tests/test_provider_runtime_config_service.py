import uuid

from app.models import ControlPlaneConfig, LLMProvider
from app.services.provider_runtime_config import (
    HOST_RUNTIME_FALLBACK_ENV,
    PROVIDER_DEFAULT_MODEL_PRECEDENCE,
    apply_provider_runtime_defaults,
    describe_host_runtime_fallback_policy,
    resolve_host_runtime_fallback_default,
    resolve_provider_default_model,
)


def test_resolve_provider_default_model_prefers_config_model_and_trims_values():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        default_model_id="  provider-model  ",
        is_global=True,
        is_active=True,
    )
    config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name="default",
        model_id="  db-model  ",
        is_active=True,
    )

    assert resolve_provider_default_model(provider, config=config, fallback_model_id="  fallback-model  ") == "db-model"


def test_resolve_provider_default_model_ignores_blank_values_before_fallback():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        default_model_id="   ",
        is_global=True,
        is_active=True,
    )
    config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name="default",
        model_id="",
        is_active=True,
    )

    assert (
        resolve_provider_default_model(provider, config=config, fallback_model_id="  fallback-model  ")
        == "fallback-model"
    )


def test_resolve_provider_default_model_uses_provider_default_without_config():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        default_model_id="  provider-model  ",
        is_global=True,
        is_active=True,
    )

    assert resolve_provider_default_model(provider, fallback_model_id="fallback-model") == "provider-model"


def test_resolve_provider_default_model_returns_none_when_all_candidates_are_blank():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        default_model_id=" ",
        is_global=True,
        is_active=True,
    )

    assert resolve_provider_default_model(provider, fallback_model_id="  ") is None


def test_provider_default_model_precedence_is_documented_and_stable():
    assert PROVIDER_DEFAULT_MODEL_PRECEDENCE == (
        "control_plane_config.model_id",
        "provider.default_model_id",
        "fallback_model_id",
    )


def test_apply_provider_runtime_defaults_does_not_mutate_input_mappings():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    config_json = {"request_timeout_seconds": 30}
    capabilities_json = {"supports_model_pull": True}

    resolved_config, resolved_capabilities = apply_provider_runtime_defaults(
        provider,
        runtime={"driver": "ollama", "runtime_kind": "local"},
        config_json=config_json,
        capabilities_json=capabilities_json,
    )

    assert config_json == {"request_timeout_seconds": 30}
    assert capabilities_json == {"supports_model_pull": True}
    assert resolved_config["request_timeout_seconds"] == 30
    assert resolved_config["default_max_tokens_per_request"] == 512
    assert resolved_capabilities["supports_model_pull"] is True


def test_host_runtime_fallback_policy_defaults_to_denied_for_production_profile():
    env = {"OCTRYX_RUNTIME_PROFILE": "production"}

    assert resolve_host_runtime_fallback_default(env=env) is False
    policy = describe_host_runtime_fallback_policy(env=env)
    assert policy["allowed_by_default"] is False
    assert policy["source"] == "default_denied"
    assert policy["production_like_profile"] is True


def test_host_runtime_fallback_policy_allows_explicit_environment_override():
    env = {"OCTRYX_RUNTIME_PROFILE": "production", HOST_RUNTIME_FALLBACK_ENV: "true"}

    assert resolve_host_runtime_fallback_default(env=env) is True
    policy = describe_host_runtime_fallback_policy(env=env)
    assert policy["allowed_by_default"] is True
    assert policy["source"] == "environment_override"


def test_apply_provider_runtime_defaults_uses_explicit_host_fallback_env(monkeypatch):
    monkeypatch.setenv(HOST_RUNTIME_FALLBACK_ENV, "1")
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )

    config_json, capabilities_json = apply_provider_runtime_defaults(
        provider,
        runtime={"driver": "ollama", "runtime_kind": "local"},
        config_json={},
    )

    assert config_json["local_runtime_allow_host_fallback"] is True
    assert capabilities_json["host_runtime_fallback_policy"]["source"] == "environment_override"


def test_apply_provider_runtime_defaults_backfills_blank_local_runtime_settings():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )

    config_json, capabilities_json = apply_provider_runtime_defaults(
        provider,
        runtime={"driver": "ollama", "runtime_kind": "local"},
        config_json={
            "local_runtime_compose_service": "   ",
            "request_timeout_seconds": "",
        },
    )

    assert config_json["local_runtime_compose_service"] == "ollama"
    assert config_json["local_runtime_allow_host_fallback"] is False
    assert config_json["request_timeout_seconds"] == 180
    assert capabilities_json["supports_model_pull"] is True


def test_apply_provider_runtime_defaults_preserves_explicit_local_host_fallback_true():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )

    config_json, capabilities_json = apply_provider_runtime_defaults(
        provider,
        runtime={"driver": "ollama", "runtime_kind": "local"},
        config_json={"local_runtime_allow_host_fallback": True},
    )

    assert config_json["local_runtime_allow_host_fallback"] is True
    assert capabilities_json["host_runtime_fallback_policy"]["allowed_by_default"] is False
