"""Prompt caching policy helpers for AWS Bedrock Converse requests."""

from __future__ import annotations

import json
from typing import Any

APPROX_CHARS_PER_TOKEN = 4
DEFAULT_CACHE_TTL = "5m"
SUPPORTED_CACHE_TTLS = {"5m", "1h"}


def _normalized_model_id(model_id: str) -> str:
    raw = str(model_id or "").strip().lower()
    if raw.startswith(("eu.", "us.", "ap.", "global.")):
        raw = raw.split(".", 1)[1]
    return raw.split(":", 1)[0]


def bedrock_prompt_cache_min_tokens(model_id: str) -> int | None:
    normalized = _normalized_model_id(model_id)
    if not normalized:
        return None
    if "claude-sonnet-4-6" in normalized:
        return 1024
    if "nova-2-lite" in normalized or "nova-lite" in normalized:
        return 1024
    if "claude-3-7-sonnet" in normalized or "claude-3-5-sonnet-20241022" in normalized:
        return 1024
    if any(
        token in normalized
        for token in (
            "claude-opus-4-5",
            "claude-opus-4-6",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
        )
    ):
        return 4096
    return None


def supports_bedrock_prompt_caching(model_id: str) -> bool:
    return bedrock_prompt_cache_min_tokens(model_id) is not None


def supports_bedrock_extended_prompt_cache_ttl(model_id: str) -> bool:
    normalized = _normalized_model_id(model_id)
    return normalized.startswith("anthropic.claude-")


def supports_bedrock_tool_prompt_caching(model_id: str) -> bool:
    normalized = _normalized_model_id(model_id)
    return normalized.startswith("anthropic.claude-")


def normalize_prompt_cache_config(config_json: dict[str, Any] | None) -> dict[str, Any]:
    raw = (config_json or {}).get("prompt_caching") if isinstance(config_json, dict) else {}
    config = raw if isinstance(raw, dict) else {}
    enabled = bool(config.get("enabled"))
    ttl = str(config.get("ttl") or DEFAULT_CACHE_TTL).strip().lower()
    if ttl not in SUPPORTED_CACHE_TTLS:
        ttl = DEFAULT_CACHE_TTL
    return {
        "enabled": enabled,
        "ttl": ttl,
        "cache_system": config.get("cache_system", True) is not False,
        "cache_tools": config.get("cache_tools", True) is not False,
        "min_tokens_override": config.get("min_tokens"),
    }


def prompt_cache_point(ttl: str = DEFAULT_CACHE_TTL) -> dict[str, Any]:
    cache_point: dict[str, Any] = {"type": "default"}
    if ttl == "1h":
        cache_point["ttl"] = "1h"
    return {"cachePoint": cache_point}


def approx_bedrock_block_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value or "")
    return max(0, len(text) // APPROX_CHARS_PER_TOKEN)


def should_add_cache_point(*, value: Any, model_id: str, min_tokens_override: Any = None) -> bool:
    min_tokens = bedrock_prompt_cache_min_tokens(model_id)
    if min_tokens is None:
        return False
    try:
        if min_tokens_override is not None:
            min_tokens = max(1, int(min_tokens_override))
    except (TypeError, ValueError):
        pass
    return approx_bedrock_block_tokens(value) >= min_tokens


__all__ = [
    "DEFAULT_CACHE_TTL",
    "approx_bedrock_block_tokens",
    "bedrock_prompt_cache_min_tokens",
    "normalize_prompt_cache_config",
    "prompt_cache_point",
    "should_add_cache_point",
    "supports_bedrock_extended_prompt_cache_ttl",
    "supports_bedrock_prompt_caching",
    "supports_bedrock_tool_prompt_caching",
]
