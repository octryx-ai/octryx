"""Canonical package surface for provider runtime config helpers."""

from .service import (
    DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST,
    DEFAULT_OLLAMA_REQUEST_TIMEOUT_SECONDS,
    HOST_RUNTIME_FALLBACK_ENV,
    PROVIDER_DEFAULT_MODEL_PRECEDENCE,
    apply_provider_runtime_defaults,
    default_provider_profile_home,
    describe_host_runtime_fallback_policy,
    parse_provider_runtime_bool,
    resolve_host_runtime_fallback_default,
    resolve_provider_default_model,
)

__all__ = [
    "DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST",
    "DEFAULT_OLLAMA_REQUEST_TIMEOUT_SECONDS",
    "HOST_RUNTIME_FALLBACK_ENV",
    "PROVIDER_DEFAULT_MODEL_PRECEDENCE",
    "apply_provider_runtime_defaults",
    "default_provider_profile_home",
    "describe_host_runtime_fallback_policy",
    "parse_provider_runtime_bool",
    "resolve_host_runtime_fallback_default",
    "resolve_provider_default_model",
]
