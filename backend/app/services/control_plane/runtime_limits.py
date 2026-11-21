"""Runtime request/token limit helpers for control-plane runtimes."""

from __future__ import annotations

from app.services.control_plane.constants import (
    DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST,
    DEFAULT_OLLAMA_RUNTIME_REQUEST_TIMEOUT_SECONDS,
)

from ...models import ControlPlaneConfig, LLMProvider
from ...models.runtime.llm_provider import LLMModel


def runtime_request_timeout_seconds(provider: LLMProvider | None) -> float | None:
    if not provider:
        return None
    config = provider.config_json if isinstance(provider.config_json, dict) else {}
    raw_value = config.get("request_timeout_seconds")
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        parsed = (
            DEFAULT_OLLAMA_RUNTIME_REQUEST_TIMEOUT_SECONDS
            if getattr(provider, "driver", "") == "ollama"
            else 0.0
        )
    return parsed if parsed > 0 else None


def runtime_max_tokens_per_request(
    provider: LLMProvider | None,
    model: LLMModel | None,
    config: ControlPlaneConfig | None,
) -> int | None:
    if model and getattr(model, "max_tokens_per_request", None):
        return getattr(model, "max_tokens_per_request", None)
    provider_config = provider.config_json if provider and isinstance(provider.config_json, dict) else {}
    if provider and getattr(provider, "driver", "") == "ollama":
        try:
            parsed = int(provider_config.get("default_max_tokens_per_request") or DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST)
        except (TypeError, ValueError):
            parsed = DEFAULT_OLLAMA_MAX_TOKENS_PER_REQUEST
        return max(128, parsed)
    return getattr(config, "max_output_tokens_default", None)
