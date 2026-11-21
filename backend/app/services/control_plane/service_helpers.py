"""Control plane helpers that take no injected collaborators.

:mod:`app.services.control_plane_service` imports them and passes them to the implementations it wraps.
"""

from __future__ import annotations

from app.services.control_plane.config import (
    is_seed_runtime_target as _is_seed_runtime_target_impl,
)
from app.services.control_plane.constants import (
    settings,
)
from app.services.control_plane.provider_auth import (
    get_provider_auth_mode as _get_provider_auth_mode_impl,
)
from app.services.control_plane.provider_auth import (
    provider_secret_scope as _provider_secret_scope_impl,
)
from app.services.control_plane.runtime_limits import (
    runtime_max_tokens_per_request as _runtime_max_tokens_per_request_impl,
)
from app.services.control_plane.runtime_limits import (
    runtime_request_timeout_seconds as _runtime_request_timeout_seconds_impl,
)

from ...agent.providers import CopilotClient, infer_provider_runtime
from ...models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider
from ...models.runtime.llm_provider import LLMModel


def provider_secret_scope(provider: LLMProvider | None, field_name: str = "api_key") -> tuple[str, str]:
    return _provider_secret_scope_impl(provider, field_name)


def get_provider_auth_mode(provider: LLMProvider | None) -> str:
    return _get_provider_auth_mode_impl(provider, infer_provider_runtime_func=infer_provider_runtime)


def _runtime_request_timeout_seconds(provider: LLMProvider | None) -> float | None:
    return _runtime_request_timeout_seconds_impl(provider)


def _runtime_max_tokens_per_request(
    provider: LLMProvider | None,
    model: LLMModel | None,
    config: ControlPlaneConfig | None,
) -> int | None:
    return _runtime_max_tokens_per_request_impl(provider, model, config)


def _is_seed_runtime_target(target: ControlPlaneRuntimeTarget, provider: LLMProvider | None) -> bool:
    return _is_seed_runtime_target_impl(target, provider, settings=settings)


def get_copilot_auth_session_info() -> dict[str, str | bool]:
    return CopilotClient.detect_auth_session()
