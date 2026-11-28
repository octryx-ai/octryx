import uuid

from app.models import ControlPlaneConfig, LLMProvider
from app.services.provider_runtime_config import PROVIDER_DEFAULT_MODEL_PRECEDENCE, resolve_provider_default_model


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
