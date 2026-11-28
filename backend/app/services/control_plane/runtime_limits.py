"""Runtime request/token limit helpers for control-plane runtimes."""

from __future__ import annotations

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
        return None
    return parsed if parsed > 0 else None


def runtime_max_tokens_per_request(model: LLMModel | None, config: ControlPlaneConfig | None) -> int | None:
    if model and getattr(model, "max_tokens_per_request", None):
        return getattr(model, "max_tokens_per_request", None)
    return getattr(config, "max_output_tokens_default", None)
