"""Shared token and reasoning limits for the agent engine."""

from __future__ import annotations

from ....runtime_limits import (
    DEFAULT_APPROX_CHARS_PER_TOKEN,
    DEFAULT_EXTENDED_COMPLETION_TOKENS,
    DEFAULT_MAX_COMPLETION_TOKENS,
)

APPROX_CHARS_PER_TOKEN = DEFAULT_APPROX_CHARS_PER_TOKEN
EXTENDED_MAX_COMPLETION_TOKENS = DEFAULT_EXTENDED_COMPLETION_TOKENS


def map_reasoning_effort(thinking_level: str | None) -> str | None:
    mapping = {
        "off": None,
        "light": "low",
        "deep": "high",
    }
    return mapping.get(thinking_level or "", "medium" if thinking_level else None)


def max_completion_tokens_for_run(
    capability_type: str,
    thinking_level: str | None,
    agent_definition: dict | None,
    *,
    default_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    extended_tokens: int = EXTENDED_MAX_COMPLETION_TOKENS,
) -> int:
    if capability_type in {"change", "admin"}:
        return extended_tokens
    if (thinking_level or "").lower() == "deep":
        return extended_tokens
    if agent_definition and any(
        (step.get("stepType") or step.get("step_type")) == "documentation" for step in agent_definition.get("steps", [])
    ):
        return extended_tokens
    return default_tokens
