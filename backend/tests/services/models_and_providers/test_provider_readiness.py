"""Provider readiness contract tests."""

import pytest

from app.services.provider import (
    READINESS_NEEDS_CONFIGURATION,
    READINESS_READY,
    READINESS_UNAVAILABLE,
    READINESS_UNKNOWN,
    resolve_provider_readiness,
)
from tests.model_gateway.conftest import gateway_provider


def _readiness(**overrides) -> tuple[str, str, bool]:
    readiness = resolve_provider_readiness(gateway_provider(**overrides))
    return readiness["status"], readiness["reason"], readiness["runtime_attempt_allowed"]


def test_provider_readiness_ready_for_successful_health_check():
    readiness = resolve_provider_readiness(gateway_provider(health_status="ok"))

    assert (readiness["status"], readiness["reason"]) == (READINESS_READY, "health_check_ok")
    assert readiness["runtime_attempt_allowed"] is True
    assert readiness["driver"] == "litellm_gateway"


def test_provider_readiness_unavailable_for_failed_health_check():
    assert _readiness(health_status="error") == (READINESS_UNAVAILABLE, "health_error", False)


def test_provider_readiness_unknown_but_attemptable_before_a_health_check():
    status, _reason, allowed = _readiness()
    assert (status, allowed) == (READINESS_UNKNOWN, True)


@pytest.mark.parametrize("overrides", [{"api_key_secret_ref": None}, {"endpoint_url": None},
                                       {"endpoint_url": "", "api_key_secret_ref": None}])
def test_a_gateway_without_its_endpoint_or_key_needs_configuration(overrides):
    status, reason, allowed = _readiness(**overrides)
    assert (status, allowed) == (READINESS_NEEDS_CONFIGURATION, False)
    assert reason


def test_a_row_with_an_unsupported_driver_never_runs():
    assert _readiness(driver="openrouter_api", health_status="ok") == (
        READINESS_NEEDS_CONFIGURATION, "driver_unsupported", False)


def test_an_inactive_provider_is_unavailable():
    assert _readiness(is_active=False) == (READINESS_UNAVAILABLE, "provider_inactive", False)
