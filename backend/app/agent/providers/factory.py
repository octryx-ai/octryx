"""Provider factory – returns the correct LLM provider based on config."""

from typing import Any

from ..core.runtime.runtime_errors import RUNTIME_ERROR_PERMANENT, ProviderRuntimeError
from .base import BaseLLMProvider
from .provider_registry import SUPPORTED_DRIVERS_MESSAGE, infer_provider_runtime


def get_provider(
    provider_name: str | None = None,
    driver: str | None = None,
    endpoint_url: str | None = None,
    binary_path: str | None = None,
    profile_name: str | None = None,
    config_json: dict[str, Any] | None = None,
    api_key: str | None = None,
    region: str | None = None,
    role_arn: str | None = None,
    copilot_token: str | None = None,
    auth_mode: str | None = None,
    request_timeout_seconds: float | None = None,
    google_access_token: str | None = None,
    google_project_id: str | None = None,
    project_model_admission: Any = None,
    **_extra: Any,
) -> BaseLLMProvider:
    """
    Factory function to create an LLM provider.

    Args:
        provider_name: The provider row's name (a label; the runtime is chosen by `driver`).
        driver: The exact driver id (`provider_registry.DRIVER_SPECS`).
        api_key: OpenRouter API key (for openrouter provider).
        region: AWS region (for bedrock provider).
        role_arn: AWS role ARN for STS assume (for bedrock provider).
        copilot_token: GitHub Copilot token for explicit token auth.
        auth_mode: Optional provider auth mode hint.
        google_access_token: Google OAuth access token for Gemini API.
        google_project_id: Google Cloud project used with OAuth-authenticated Gemini API calls.
        project_model_admission: Server-owned project model-alias admission. Required by the
            governed gateway driver; ignored by every other driver.

    Returns:
        BaseLLMProvider instance.
    """
    resolved = infer_provider_runtime(name=provider_name, driver=driver, auth_mode=auth_mode)
    resolved_driver = resolved["driver"]
    resolved_auth_mode = resolved["auth_mode"]

    if not resolved_driver:
        raise ProviderRuntimeError(
            f"Unknown provider driver. Reconfigure the provider with a supported driver. {SUPPORTED_DRIVERS_MESSAGE}",
            error_class=RUNTIME_ERROR_PERMANENT,
        )

    if resolved_driver == "openrouter_api":
        from .openrouter import OpenRouterClient

        if not api_key:
            raise ValueError("OpenRouter provider requires api_key")
        return OpenRouterClient(api_key)

    elif resolved_driver == "bedrock_api":
        from .bedrock import BedrockClient

        return BedrockClient(
            region=region or "eu-central-1",
            role_arn=role_arn,
            config_json=config_json,
            aws_access_key_id=_extra.get("aws_access_key_id"),
            aws_secret_access_key=_extra.get("aws_secret_access_key"),
            aws_session_token=_extra.get("aws_session_token"),
            accepts_temperature=_extra.get("accepts_temperature"),
            target_temperature=_extra.get("target_temperature"),
        )

    elif resolved_driver == "copilot_api":
        from .copilot import CopilotClient

        explicit_token = str(copilot_token or "").strip() or None
        return CopilotClient(
            explicit_token if explicit_token or resolved_auth_mode in {"api_key", "oauth"} else None,
            base_url=endpoint_url,
        )

    elif resolved_driver == "gemini_api":
        from .google import GoogleClient

        return GoogleClient(
            api_key=api_key if resolved_auth_mode == "api_key" else None,
            access_token=google_access_token if resolved_auth_mode == "oauth" else None,
            project_id=google_project_id if resolved_auth_mode == "oauth" else None,
            request_timeout_seconds=request_timeout_seconds,
        )

    elif resolved_driver == "openai_compatible":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=endpoint_url or "",
            api_key=api_key,
            request_timeout_seconds=request_timeout_seconds,
        )

    elif resolved_driver == "litellm_gateway":
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

    elif resolved_driver == "ollama":
        from .ollama import OllamaClient

        return OllamaClient(
            base_url=endpoint_url or "http://localhost:11434",
            config_json=config_json,
            request_timeout_seconds=request_timeout_seconds,
        )

    raise ProviderRuntimeError(
        f"Provider driver {resolved_driver} has no client. {SUPPORTED_DRIVERS_MESSAGE}",
        error_class=RUNTIME_ERROR_PERMANENT,
    )
