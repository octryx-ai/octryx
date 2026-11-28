"""Canonical package surface for provider runtime config helpers."""

from .service import PROVIDER_DEFAULT_MODEL_PRECEDENCE, resolve_provider_default_model

__all__ = [
    "PROVIDER_DEFAULT_MODEL_PRECEDENCE",
    "resolve_provider_default_model",
]
