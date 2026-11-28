"""Provider readiness contract for admin display and runtime selection."""

from __future__ import annotations

from typing import Any

from ...agent.providers import get_driver_spec, infer_provider_runtime
from ...models import LLMProvider
from ..model_gateway.litellm.readiness import gateway_configuration_reason
from ..model_gateway.litellm.runtime_admission import LITELLM_GATEWAY_DRIVER

READINESS_READY = "ready"
READINESS_DEGRADED = "degraded"
READINESS_UNKNOWN = "unknown"
READINESS_UNAVAILABLE = "unavailable"
READINESS_NEEDS_CONFIGURATION = "needs_configuration"

_READY_HEALTH_STATUSES = {"ok", "ready", "success", "synced"}
_DEGRADED_HEALTH_STATUSES = {"no_models", "stale_cache"}
_UNAVAILABLE_HEALTH_STATUSES = {
    "auth_denied",
    "error",
    "failed",
    "model_sync_failed",
    "provider_unavailable",
    "stopped",
    "unavailable",
    "validation_failed",
}
_API_KEY_AUTH_MODES = {"api_key", "token", "bearer"}


def resolve_provider_readiness(provider: LLMProvider | None) -> dict[str, Any]:
    if provider is None:
        return _readiness(READINESS_UNAVAILABLE, "provider_missing", runtime_attempt_allowed=False)
    runtime = infer_provider_runtime(
        name=provider.name,
        driver=getattr(provider, "driver", None),
        provider_family=getattr(provider, "provider_family", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        auth_mode=getattr(provider, "auth_mode", None),
    )
    # A row without a supported driver id can never execute, no matter what else is
    # configured on it, so it is reported as unusable before any credential or health
    # signal is consulted.
    if not runtime["driver"]:
        return _readiness(
            READINESS_NEEDS_CONFIGURATION,
            "driver_unsupported",
            runtime_attempt_allowed=False,
            runtime=runtime,
        )
    if not provider.is_active:
        return _readiness(
            READINESS_UNAVAILABLE,
            "provider_inactive",
            runtime_attempt_allowed=False,
            runtime=runtime,
        )
    # A governed gateway owns its whole configuration contract, so its specific
    # reason wins over the generic endpoint/API-key checks.
    missing_config_reason = (
        _missing_gateway_contract_reason(provider, runtime)
        or _missing_endpoint_reason(provider, runtime)
        or _missing_auth_reason(provider, runtime)
    )
    if missing_config_reason:
        return _readiness(
            READINESS_NEEDS_CONFIGURATION,
            missing_config_reason,
            runtime_attempt_allowed=False,
            runtime=runtime,
        )
    health_status = str(getattr(provider, "health_status", "") or "").strip().lower()
    if health_status in _READY_HEALTH_STATUSES:
        return _readiness(READINESS_READY, "health_check_ok", runtime_attempt_allowed=True, runtime=runtime)
    if health_status in _DEGRADED_HEALTH_STATUSES:
        return _readiness(READINESS_DEGRADED, health_status, runtime_attempt_allowed=True, runtime=runtime)
    if health_status in _UNAVAILABLE_HEALTH_STATUSES:
        return _readiness(
            READINESS_UNAVAILABLE,
            f"health_{health_status}",
            runtime_attempt_allowed=False,
            runtime=runtime,
        )
    if health_status:
        return _readiness(
            READINESS_UNKNOWN,
            "health_status_unrecognized",
            runtime_attempt_allowed=True,
            runtime=runtime,
        )
    return _readiness(
        READINESS_UNKNOWN,
        "health_unchecked",
        runtime_attempt_allowed=True,
        runtime=runtime,
    )


def _missing_endpoint_reason(provider: LLMProvider, runtime: dict[str, str]) -> str | None:
    spec = get_driver_spec(runtime["driver"])
    if spec is None or not spec.requires_endpoint_url:
        return None
    if str(getattr(provider, "endpoint_url", "") or "").strip():
        return None
    return "endpoint_url_not_configured"


def _missing_gateway_contract_reason(provider: LLMProvider, runtime: dict[str, str]) -> str | None:
    if runtime["driver"] != LITELLM_GATEWAY_DRIVER:
        return None
    return gateway_configuration_reason(provider) or None


def _missing_auth_reason(provider: LLMProvider, runtime: dict[str, str]) -> str | None:
    auth_mode = str(provider.auth_mode or runtime.get("auth_mode") or "").strip().lower()
    if auth_mode in {"oauth", "auth_session", "profile", "none"}:
        return None
    if auth_mode in _API_KEY_AUTH_MODES and not _provider_has_api_key(provider):
        return "api_key_not_configured"
    return None


def _provider_has_api_key(provider: LLMProvider) -> bool:
    return bool(str(getattr(provider, "api_key_secret_ref", "") or "").strip())


def _readiness(
    status: str,
    reason: str,
    *,
    runtime_attempt_allowed: bool,
    runtime: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "runtime_attempt_allowed": runtime_attempt_allowed,
        "provider_family": (runtime or {}).get("provider_family"),
        "driver": (runtime or {}).get("driver"),
        "runtime_kind": (runtime or {}).get("runtime_kind"),
    }


__all__ = [
    "READINESS_DEGRADED",
    "READINESS_NEEDS_CONFIGURATION",
    "READINESS_READY",
    "READINESS_UNAVAILABLE",
    "READINESS_UNKNOWN",
    "resolve_provider_readiness",
]
