"""Control plane helpers that take no injected collaborators."""

from __future__ import annotations

from app.services.control_plane.config import (
    is_seed_runtime_target as _is_seed_runtime_target_impl,
)
from app.services.control_plane.constants import (
    settings,
)
from app.services.control_plane.provider_auth import (
    provider_secret_scope as _provider_secret_scope_impl,
)
from app.services.control_plane.runtime_limits import (
    runtime_request_timeout_seconds as _runtime_request_timeout_seconds_impl,
)

from ...models import ControlPlaneRuntimeTarget, LLMProvider


def provider_secret_scope(provider: LLMProvider | None, field_name: str = "api_key") -> tuple[str, str]:
    return _provider_secret_scope_impl(provider, field_name)


def _runtime_request_timeout_seconds(provider: LLMProvider | None) -> float | None:
    return _runtime_request_timeout_seconds_impl(provider)


def _is_seed_runtime_target(target: ControlPlaneRuntimeTarget, provider: LLMProvider | None) -> bool:
    return _is_seed_runtime_target_impl(target, provider, settings=settings)

