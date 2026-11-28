"""Helpers for provider runtime defaults."""

from __future__ import annotations

from typing import Any

from ...models import ControlPlaneConfig, LLMProvider

PROVIDER_DEFAULT_MODEL_PRECEDENCE = (
    "control_plane_config.model_id",
    "provider.default_model_id",
    "fallback_model_id",
)


def _normalize_non_empty_string(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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
    """Resolve the provider default model from the canonical precedence order."""

    for candidate in _provider_default_model_candidates(
        provider,
        config=config,
        fallback_model_id=fallback_model_id,
    ):
        normalized = _normalize_non_empty_string(candidate)
        if normalized is not None:
            return normalized
    return None
