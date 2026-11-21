"""Bootstrap state assembly helpers for local bootstrap services."""

from __future__ import annotations

from typing import Any

from ...models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider


def serialize_bootstrap_state(
    *,
    provider: LLMProvider | None,
    runtime_target: ControlPlaneRuntimeTarget | None,
    installed_model: LLMModel | None,
    resolved_model_id: str | None = None,
    available_models: list[str] | None = None,
    default_local_bootstrap_model: str,
    default_local_bootstrap_display_name: str,
    default_local_bootstrap_profile: str,
    default_ollama_base_url_func,
) -> dict[str, Any]:
    model_id = (
        installed_model.model_id
        if installed_model is not None
        else resolved_model_id
        if resolved_model_id
        else (provider.default_model_id if provider and provider.default_model_id else default_local_bootstrap_model)
    )
    available = list(available_models or [])
    installed = bool(installed_model and installed_model.is_active)
    return {
        "provider_id": provider.id if provider else "",
        "provider_display_name": (
            provider.display_name if provider and provider.display_name else default_local_bootstrap_display_name
        ),
        "endpoint_url": (
            provider.endpoint_url if provider and provider.endpoint_url else default_ollama_base_url_func()
        ),
        "profile_name": (
            provider.profile_name if provider and provider.profile_name else default_local_bootstrap_profile
        ),
        "model_id": model_id,
        "bootstrap_role": provider.bootstrap_role if provider and provider.bootstrap_role else "",
        "health_status": provider.health_status if provider and provider.health_status else "",
        "last_health_check_at": (
            provider.last_health_check_at.isoformat() if provider and provider.last_health_check_at else ""
        ),
        "last_health_error": provider.last_health_error if provider and provider.last_health_error else "",
        "runtime_target_id": runtime_target.id if runtime_target else "",
        "runtime_priority": runtime_target.priority if runtime_target else None,
        "is_primary": bool(runtime_target and runtime_target.priority == 1 and runtime_target.is_active),
        "installed": installed,
        "setup_complete": bool(provider and runtime_target and installed),
        "available_models": available,
        "managed_by_system": bool(provider and provider.bootstrap_role == "default_anchor"),
        "recommended_endpoint_url": (
            provider.endpoint_url if provider and provider.endpoint_url else default_ollama_base_url_func()
        ),
        "recommended_model_id": model_id or default_local_bootstrap_model,
    }
