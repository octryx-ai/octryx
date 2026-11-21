"""Provider readiness contract tests."""

import uuid

from app.models import LLMProvider
from app.services.provider import (
    READINESS_NEEDS_CONFIGURATION,
    READINESS_READY,
    READINESS_UNAVAILABLE,
    READINESS_UNKNOWN,
    resolve_provider_readiness,
)


def test_provider_readiness_ready_for_successful_health_check():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        health_status="ok",
        is_active=True,
    )

    readiness = resolve_provider_readiness(provider)

    assert readiness["status"] == READINESS_READY
    assert readiness["reason"] == "health_check_ok"
    assert readiness["runtime_attempt_allowed"] is True
    assert readiness["driver"] == "ollama"


def test_provider_readiness_needs_configuration_for_missing_api_key():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        provider_family="openrouter",
        driver="openrouter_api",
        runtime_kind="api",
        auth_mode="api_key",
        is_active=True,
    )

    readiness = resolve_provider_readiness(provider)

    assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
    assert readiness["reason"] == "api_key_not_configured"
    assert readiness["runtime_attempt_allowed"] is False


def test_provider_readiness_unavailable_for_failed_health_check():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        health_status="error",
        is_active=True,
    )

    readiness = resolve_provider_readiness(provider)

    assert readiness["status"] == READINESS_UNAVAILABLE
    assert readiness["reason"] == "health_error"
    assert readiness["runtime_attempt_allowed"] is False


def test_provider_readiness_unknown_but_attemptable_for_remote_provider_without_native_health_check():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        provider_family="openrouter",
        driver="openrouter_api",
        runtime_kind="api",
        auth_mode="api_key",
        api_key_secret_ref="provider/openrouter/api_key",
        is_active=True,
    )

    readiness = resolve_provider_readiness(provider)

    assert readiness["status"] == READINESS_UNKNOWN
    assert readiness["reason"] == "health_not_required"
    assert readiness["runtime_attempt_allowed"] is True


def _openai_compatible_provider(**overrides) -> LLMProvider:
    defaults = dict(
        id=str(uuid.uuid4()),
        name="minimax",
        display_name="MiniMax",
        provider_family="openai",
        driver="openai_compatible",
        runtime_kind="api",
        auth_mode="api_key",
        endpoint_url="https://api.minimax.io/v1",
        api_key_secret_ref="provider/minimax/api_key",
        is_active=True,
    )
    defaults.update(overrides)
    return LLMProvider(**defaults)


def test_openai_compatible_ready_with_endpoint_and_key():
    readiness = resolve_provider_readiness(_openai_compatible_provider())

    assert readiness["status"] == READINESS_UNKNOWN
    assert readiness["reason"] == "health_not_required"
    assert readiness["runtime_attempt_allowed"] is True
    assert readiness["driver"] == "openai_compatible"


def test_openai_compatible_not_ready_without_endpoint_url():
    readiness = resolve_provider_readiness(_openai_compatible_provider(endpoint_url=None))

    assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
    assert readiness["reason"] == "endpoint_url_not_configured"
    assert readiness["runtime_attempt_allowed"] is False


def test_openai_compatible_not_ready_without_api_key():
    readiness = resolve_provider_readiness(_openai_compatible_provider(api_key_secret_ref=None))

    assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
    assert readiness["reason"] == "api_key_not_configured"
    assert readiness["runtime_attempt_allowed"] is False


def test_openai_compatible_missing_endpoint_reported_before_missing_key():
    readiness = resolve_provider_readiness(
        _openai_compatible_provider(endpoint_url="", api_key_secret_ref=None)
    )

    assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
    assert readiness["reason"] == "endpoint_url_not_configured"
