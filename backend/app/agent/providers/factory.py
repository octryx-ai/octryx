"""Provider factory – returns the correct LLM provider based on config."""

from typing import Any

from app.agent.runtime.runtime_errors import RUNTIME_ERROR_PERMANENT, ProviderRuntimeError

from .base import BaseLLMProvider
from .provider_registry import SUPPORTED_DRIVERS_MESSAGE, infer_provider_runtime


def get_provider(
    provider_name: str | None = None,
    driver: str | None = None,
    endpoint_url: str | None = None,
    config_json: dict[str, Any] | None = None,
    api_key: str | None = None,
    auth_mode: str | None = None,
    request_timeout_seconds: float | None = None,
    project_model_admission: Any = None,
    **_extra: Any,
) -> BaseLLMProvider:
    """The LiteLLM gateway client of a provider row; ``project_model_admission`` is required (a missing one denies)."""
    resolved = infer_provider_runtime(name=provider_name, driver=driver, auth_mode=auth_mode)
    resolved_driver = resolved["driver"]

    if not resolved_driver:
        raise ProviderRuntimeError(
            f"Unknown provider driver. Reconfigure the provider with a supported driver. {SUPPORTED_DRIVERS_MESSAGE}",
            error_class=RUNTIME_ERROR_PERMANENT,
        )

    if resolved_driver == "litellm_gateway":
        from .litellm_gateway import LiteLLMGatewayClient

        # The governed gateway adapter validates project admission, endpoint,
        # virtual key, alias catalog, and probe contract in its constructor, so
        # nothing is defaulted here. A missing admission is a denial, not a
        # permissive default.
        return LiteLLMGatewayClient(
            endpoint_url=endpoint_url,
            project_admission=project_model_admission,
            api_key=api_key,
            config_json=config_json,
            request_timeout_seconds=request_timeout_seconds,
            accepts_temperature=_extra.get("accepts_temperature"),
            target_temperature=_extra.get("target_temperature"),
        )

    raise ProviderRuntimeError(
        f"Provider driver {resolved_driver} has no client. {SUPPORTED_DRIVERS_MESSAGE}",
        error_class=RUNTIME_ERROR_PERMANENT,
    )
