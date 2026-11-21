"""Helpers for provider runtime defaults and managed profile metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ...agent.providers import infer_provider_runtime
from ...models import ControlPlaneConfig, LLMProvider

DEFAULT_OLLAMA_REQUEST_TIMEOUT_SECONDS = 180
DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST = 512
HOST_RUNTIME_FALLBACK_ENV = "OCTRYX_ALLOW_HOST_RUNTIME_FALLBACK"
RUNTIME_PROFILE_ENV = "OCTRYX_RUNTIME_PROFILE"
OCTRYX_ENV_ENV = "OCTRYX_ENV"
APP_ENV_ENV = "APP_ENV"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_PRODUCTION_LIKE_PROFILES = {"prod", "production", "prd", "live", "stage", "staging", "non-prod", "nonprod"}
PROVIDER_DEFAULT_MODEL_PRECEDENCE = (
    "control_plane_config.model_id",
    "provider.default_model_id",
    "fallback_model_id",
)


def default_provider_profile_home(provider_id: str) -> str:
    return f"/app/data/provider_profiles/{provider_id}/home"


def _normalize_non_empty_string(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _is_blank_runtime_default(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _setdefault_if_blank(mapping: dict[str, Any], key: str, value: Any) -> None:
    if key not in mapping or _is_blank_runtime_default(mapping.get(key)):
        mapping[key] = value


def _parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def parse_provider_runtime_bool(value: Any, *, default: bool = False) -> bool:
    parsed = _parse_optional_bool(value)
    return default if parsed is None else parsed


def _runtime_profile(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return str(
        source.get(RUNTIME_PROFILE_ENV)
        or source.get(OCTRYX_ENV_ENV)
        or source.get(APP_ENV_ENV)
        or ""
    ).strip().lower()


def resolve_host_runtime_fallback_default(env: Mapping[str, str] | None = None) -> bool:
    """Default-deny host fallback unless an operator explicitly opts in."""

    source = os.environ if env is None else env
    explicit = _parse_optional_bool(source.get(HOST_RUNTIME_FALLBACK_ENV))
    if explicit is not None:
        return explicit
    return False


def describe_host_runtime_fallback_policy(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if env is None else env
    explicit = _parse_optional_bool(source.get(HOST_RUNTIME_FALLBACK_ENV))
    profile = _runtime_profile(source)
    if explicit is not None:
        source_label = "environment_override"
        allowed = explicit
    else:
        source_label = "default_denied"
        allowed = False
    return {
        "allowed_by_default": allowed,
        "source": source_label,
        "runtime_profile": profile,
        "production_like_profile": profile in _PRODUCTION_LIKE_PROFILES,
        "override_env": HOST_RUNTIME_FALLBACK_ENV,
    }


def _provider_default_model_candidates(
    provider: LLMProvider | None,
    *,
    config: ControlPlaneConfig | None = None,
    fallback_model_id: str | None = None,
) -> tuple[Any, ...]:
    return (
        config.model_id if config else None,
        provider.default_model_id if provider else None,
        fallback_model_id,
    )


def resolve_provider_default_model(
    provider: LLMProvider | None,
    *,
    config: ControlPlaneConfig | None = None,
    fallback_model_id: str | None = None,
) -> str | None:
    """Resolve the provider default model from the canonical precedence order.

    The helper is intentionally narrow:

    1. `control_plane_config.model_id`
    2. `provider.default_model_id`
    3. explicit `fallback_model_id`

    It trims blank values and keeps the caller's own choice of fallback.
    It does not validate whether the resolved model belongs to a specific provider.
    """

    for candidate in _provider_default_model_candidates(
        provider,
        config=config,
        fallback_model_id=fallback_model_id,
    ):
        normalized = _normalize_non_empty_string(candidate)
        if normalized is not None:
            return normalized
    return None


def apply_provider_runtime_defaults(
    provider: LLMProvider,
    *,
    runtime: dict[str, str] | None = None,
    config_json: dict[str, Any] | None = None,
    capabilities_json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = runtime or infer_provider_runtime(
        name=provider.name,
        driver=getattr(provider, "driver", None),
        provider_family=getattr(provider, "provider_family", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        auth_mode=provider.auth_mode,
    )
    config = dict(config_json) if isinstance(config_json, dict) else {}
    capabilities = dict(capabilities_json) if isinstance(capabilities_json, dict) else {}

    if resolved["driver"] == "ollama":
        fallback_policy = describe_host_runtime_fallback_policy()
        _setdefault_if_blank(config, "managed_local", True)
        _setdefault_if_blank(config, "local_runtime_strategy", "docker_compose")
        _setdefault_if_blank(config, "local_runtime_auto_start", True)
        _setdefault_if_blank(config, "local_runtime_allow_host_fallback", fallback_policy["allowed_by_default"])
        _setdefault_if_blank(config, "local_runtime_compose_service", "ollama")
        _setdefault_if_blank(config, "local_runtime_compose_profile", "")
        _setdefault_if_blank(config, "request_timeout_seconds", DEFAULT_OLLAMA_REQUEST_TIMEOUT_SECONDS)
        _setdefault_if_blank(config, "default_max_tokens_per_request", DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST)
        capabilities.setdefault("host_runtime_fallback_policy", fallback_policy)
        capabilities.setdefault("supports_health_check", True)
        capabilities.setdefault("supports_model_pull", True)

    return config, capabilities
