"""The one model a fresh install declares in its environment: ``LLM_PROVIDER`` names the provider,
``AGENT_DEFAULT_MODEL`` the model; the first start makes it a route of the bundled LiteLLM and the default."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

# The values a first start can turn into a working model, each with what it reads (the message names them).
SUPPORTED = {
    "anthropic": "LLM_API_KEY",
    "openai": "LLM_API_KEY (and LLM_ENDPOINT_URL for another OpenAI-compatible server)",
    "bedrock": "AWS_REGION and AWS credentials",
    "openrouter": "OPENROUTER_API_KEY",
}
_NOT_ALIAS = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class EnvModelAccess:
    provider_type: str
    model: str
    alias: str
    credentials: dict[str, str] = field(default_factory=dict)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _alias(model: str) -> str:
    return _NOT_ALIAS.sub("-", model.lower()).strip("-.")[:63] or "default"


def env_model_access_problem(settings: Any) -> str:
    kind = _clean(settings.llm_provider).lower()
    if not kind or kind in SUPPORTED:
        return ""
    choices = "; ".join(f"{name} ({reads})" for name, reads in SUPPORTED.items())
    return (f"LLM_PROVIDER={_clean(settings.llm_provider)} is not supported, so no model was created. "
            f"Use one of: {choices}. Or leave LLM_PROVIDER empty and add a model under Admin › Models.")


def env_model_access(settings: Any) -> EnvModelAccess | None:
    kind = _clean(settings.llm_provider).lower()
    model = _clean(settings.agent_default_model)
    if kind not in SUPPORTED or not model:
        return None
    api_key = _clean(settings.llm_api_key)
    if kind == "anthropic":
        return EnvModelAccess("anthropic", model, _alias(model), {"api_key": api_key})
    if kind == "openai":
        endpoint = _clean(settings.llm_endpoint_url)
        if endpoint:
            return EnvModelAccess("openai_compatible", model, _alias(model), {"api_base": endpoint, "api_key": api_key})
        return EnvModelAccess("openai", model, _alias(model), {"api_key": api_key})
    if kind == "openrouter":
        return EnvModelAccess("openrouter", model, _alias(model),
                              {"api_key": _clean(settings.openrouter_api_key) or api_key})
    # The AWS keys are the standard environment variables (no settings field): LiteLLM gets them as the route's own.
    credentials = {"aws_region_name": _clean(settings.aws_region), "aws_access_key_id": _clean(os.environ.get("AWS_ACCESS_KEY_ID")),
                   "aws_secret_access_key": _clean(os.environ.get("AWS_SECRET_ACCESS_KEY")),
                   "aws_session_token": _clean(os.environ.get("AWS_SESSION_TOKEN"))}
    return EnvModelAccess("bedrock", model, _alias(model), {key: value for key, value in credentials.items() if value})


__all__ = ["SUPPORTED", "EnvModelAccess", "env_model_access", "env_model_access_problem"]
