"""Helpers for project/runtime policy bundles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..security_analyzer import normalize_security_analyzer_chain

_ALLOWED_RUNTIME_POLICY_FIELDS = {
    "execution_runtime_provider",
    "execution_runtime_docker_image",
    "execution_runtime_docker_network_mode",
    "execution_runtime_allow_host_fallback",
    "execution_runtime_sandbox_mode",
    "execution_runtime_docker_memory_mb",
    "execution_runtime_docker_pids_limit",
    "security_analyzer_chain",
    "security_review_model",
    "llm_security_analyzer_timeout_seconds",
    "llm_security_analyzer_review_threshold",
    "llm_security_analyzer_deny_threshold",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(minimum, min(parsed, maximum))


def normalize_runtime_policy_bundle(bundle: Mapping[str, Any] | None) -> dict[str, Any]:
    bundle = bundle or {}
    normalized: dict[str, Any] = {}
    for key in _ALLOWED_RUNTIME_POLICY_FIELDS:
        if key not in bundle:
            continue
        value = bundle.get(key)
        if key == "security_analyzer_chain":
            normalized[key] = normalize_security_analyzer_chain(value)
        elif key == "execution_runtime_provider":
            text = str(value or "").strip().lower()
            if text in {"host", "docker"}:
                normalized[key] = text
        elif key == "execution_runtime_docker_network_mode":
            text = str(value or "").strip().lower()
            if text in {"none", "bridge", "host"}:
                normalized[key] = text
        elif key == "execution_runtime_allow_host_fallback":
            normalized[key] = _as_bool(value, False)
        elif key == "execution_runtime_sandbox_mode":
            text = str(value or "").strip().lower()
            if text in {"compat", "hard"}:
                normalized[key] = text
        elif key == "execution_runtime_docker_memory_mb":
            parsed = _bounded_int(value, minimum=128, maximum=8192)
            if parsed is not None:
                normalized[key] = parsed
        elif key == "execution_runtime_docker_pids_limit":
            parsed = _bounded_int(value, minimum=32, maximum=4096)
            if parsed is not None:
                normalized[key] = parsed
        elif key in {"execution_runtime_docker_image", "security_review_model"}:
            text = str(value or "").strip()
            if text:
                normalized[key] = text
        elif key == "llm_security_analyzer_timeout_seconds":
            parsed = _bounded_int(value, minimum=1, maximum=60)
            if parsed is not None:
                normalized[key] = parsed
        elif key in {"llm_security_analyzer_review_threshold", "llm_security_analyzer_deny_threshold"}:
            parsed = _bounded_int(value, minimum=0, maximum=100)
            if parsed is not None:
                normalized[key] = parsed
    review = normalized.get("llm_security_analyzer_review_threshold")
    deny = normalized.get("llm_security_analyzer_deny_threshold")
    if isinstance(review, int) and isinstance(deny, int) and deny < review:
        normalized["llm_security_analyzer_deny_threshold"] = review
    if normalized.get("execution_runtime_sandbox_mode") == "hard":
        normalized["execution_runtime_allow_host_fallback"] = False
        if normalized.get("execution_runtime_docker_network_mode") == "host":
            normalized["execution_runtime_docker_network_mode"] = "bridge"
    return normalized


def normalize_runtime_policy_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    active_environment = str(config.get("active_environment") or "").strip()
    default_bundle = normalize_runtime_policy_bundle(
        config.get("default_bundle") if isinstance(config.get("default_bundle"), dict) else {}
    )
    environment_bundles_raw = config.get("environment_bundles")
    environment_bundles: dict[str, dict[str, Any]] = {}
    if isinstance(environment_bundles_raw, dict):
        for env_name, bundle in environment_bundles_raw.items():
            env_key = str(env_name or "").strip()
            if not env_key or not isinstance(bundle, dict):
                continue
            environment_bundles[env_key] = normalize_runtime_policy_bundle(bundle)
    return {
        "active_environment": active_environment,
        "default_bundle": default_bundle,
        "environment_bundles": environment_bundles,
    }


def resolve_runtime_policy_bundle(project_config: Mapping[str, Any] | None) -> dict[str, Any]:
    config = dict(project_config or {})
    runtime_policy = normalize_runtime_policy_config(
        config.get("runtime_policy") if isinstance(config.get("runtime_policy"), dict) else {}
    )
    active_environment = str(runtime_policy.get("active_environment") or config.get("environment_name") or "").strip()
    effective_bundle = dict(runtime_policy.get("default_bundle") or {})
    if active_environment:
        effective_bundle.update(
            normalize_runtime_policy_bundle(
                (runtime_policy.get("environment_bundles") or {}).get(active_environment) or {}
            )
        )
    return {
        "active_environment": active_environment,
        "default_bundle": dict(runtime_policy.get("default_bundle") or {}),
        "environment_bundles": dict(runtime_policy.get("environment_bundles") or {}),
        "effective_bundle": effective_bundle,
    }


def apply_runtime_policy_bundle(project_config: Mapping[str, Any] | None) -> dict[str, Any]:
    config = dict(project_config or {})
    resolved = resolve_runtime_policy_bundle(config)
    effective_bundle = dict(resolved.get("effective_bundle") or {})
    if effective_bundle:
        config.update(effective_bundle)
    config["runtime_policy"] = {
        "active_environment": resolved.get("active_environment") or "",
        "default_bundle": dict(resolved.get("default_bundle") or {}),
        "environment_bundles": dict(resolved.get("environment_bundles") or {}),
    }
    config["effective_runtime_policy"] = effective_bundle
    return config
