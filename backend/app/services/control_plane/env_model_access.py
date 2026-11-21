"""The one model access a fresh install declares in its environment.

``LLM_PROVIDER`` names it, ``AGENT_DEFAULT_MODEL`` the model. On the first start, while no runtime
target exists, ``ensure_default_control_plane_provider`` turns this into one global provider plus its
target; afterwards the admin UI owns the configuration and the environment is not read again.

- ``bedrock``: ``AWS_REGION`` and the AWS default credential chain (keys, ``AWS_PROFILE``, IRSA).
- ``anthropic``: ``LLM_API_KEY``, through Anthropic's OpenAI-compatible endpoint.
- ``openai``: ``LLM_ENDPOINT_URL`` + ``LLM_API_KEY``, any OpenAI-compatible server.
- ``openrouter``: ``OPENROUTER_API_KEY`` (or ``LLM_API_KEY``).

Any other value creates nothing: a provider without a driver would make the first model call
fail far from the cause. :func:`env_model_access_problem` names the value and the supported ones for the start log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANTHROPIC_OPENAI_COMPATIBLE_ENDPOINT = "https://api.anthropic.com/v1"
OPENAI_COMPATIBLE_DRIVER = "openai_compatible"
# The values a first start can turn into a working provider, each with what it reads (the message names them).
SUPPORTED = {
    "anthropic": "LLM_API_KEY",
    "openai": "LLM_ENDPOINT_URL and LLM_API_KEY",
    "bedrock": "AWS_REGION and AWS credentials",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class EnvModelAccess:
    name: str
    display_name: str
    driver: str
    endpoint_url: str | None
    api_key: str | None


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _kind(settings: Any) -> str:
    kind = (settings.llm_provider or "").strip().lower()
    return "openai" if kind == OPENAI_COMPATIBLE_DRIVER else kind


def env_model_access_problem(settings: Any) -> str:
    """Why ``LLM_PROVIDER`` gives no model access although it is set, or ``""``."""
    kind = _kind(settings)
    if not kind or kind in SUPPORTED:
        return ""
    choices = "; ".join(f"{name} ({reads})" for name, reads in SUPPORTED.items())
    return (f"LLM_PROVIDER={settings.llm_provider.strip()} is not supported, so no model access was created. "
            f"Use one of: {choices}. Or leave LLM_PROVIDER empty and add a provider under Admin › Models › Providers "
            "(Claude also through a Claude Code seat, AWS Bedrock, OpenRouter or a LiteLLM gateway).")


def env_model_access(settings: Any) -> EnvModelAccess | None:
    kind = _kind(settings)
    if not kind or kind not in SUPPORTED:
        return None
    api_key = _clean(settings.llm_api_key)
    if kind == "anthropic":
        endpoint = _clean(settings.llm_endpoint_url) or ANTHROPIC_OPENAI_COMPATIBLE_ENDPOINT
        return EnvModelAccess(kind, "Anthropic (Default)", OPENAI_COMPATIBLE_DRIVER, endpoint, api_key)
    if kind == "openai":
        return EnvModelAccess(
            "openai", "OpenAI-compatible (Default)", OPENAI_COMPATIBLE_DRIVER, _clean(settings.llm_endpoint_url), api_key
        )
    if kind == "openrouter":
        return EnvModelAccess(
            kind, "Openrouter (Default)", "openrouter_api", None, _clean(settings.openrouter_api_key) or api_key
        )
    return EnvModelAccess(kind, "Bedrock (Default)", "bedrock_api", None, None)
