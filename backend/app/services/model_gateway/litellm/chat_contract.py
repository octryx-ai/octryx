"""The chat-completions request a gateway call sends and the served answer it accepts (``client``).

Every failure is raised with ``from None`` so no exception survives as ``__context__`` or ``__cause__``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .alias_catalog import CAPABILITY_REASONING, CAPABILITY_TOOLS, AliasEntry
from .errors import (
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    LiteLLMGatewayError,
)

CONTRACT_DENIAL_MISSING_CHOICES = "response_missing_choices"
CONTRACT_DENIAL_MISSING_MESSAGE = "response_missing_message"
CONTRACT_DENIAL_MISSING_MODEL = "response_missing_model"


def required_capabilities(tools: list[dict[str, Any]] | None, reasoning_effort: str | None) -> frozenset[str]:
    """The capabilities the alias must have proven before this call may be sent."""
    required: set[str] = set()
    if tools:
        required.add(CAPABILITY_TOOLS)
    if reasoning_effort:
        required.add(CAPABILITY_REASONING)
    return frozenset(required)


def chat_payload(
    entry: AliasEntry,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    temperature: float | None,
    max_tokens: int,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": entry.model_group,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    # Only an explicit temperature is sent: Opus 5.5 and Sonnet 5 on Bedrock reject any temperature
    # but their default ("`temperature` is deprecated for this model" / "Only temperature=1 is supported").
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
    if reasoning_effort:
        # LiteLLM's chat-completions parameter; it maps the effort onto each provider's thinking. A Responses-style
        # ``reasoning`` object passes through to Bedrock unchanged and is refused there (live: Opus 5.5, HTTP 400).
        payload["reasoning_effort"] = reasoning_effort
    return payload


def served_message(entry: AliasEntry, body: Mapping[str, Any]) -> Mapping[str, Any]:
    """The answer's message, once the served model group is the admitted one and the shape is the contract's."""
    returned_model = str(body.get("model") or "").strip()
    if not returned_model:
        raise LiteLLMGatewayError(
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            denial_reason=CONTRACT_DENIAL_MISSING_MODEL,
        ) from None
    if returned_model != entry.model_group:
        # The gateway served a different model group than the admitted
        # alias. The content is discarded, not repaired and not retried.
        raise LiteLLMGatewayError(GATEWAY_STATE_FALLBACK_VIOLATION) from None

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise LiteLLMGatewayError(
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            denial_reason=CONTRACT_DENIAL_MISSING_CHOICES,
        ) from None
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise LiteLLMGatewayError(
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            denial_reason=CONTRACT_DENIAL_MISSING_MESSAGE,
        ) from None
    return message


__all__ = [
    "CONTRACT_DENIAL_MISSING_CHOICES",
    "CONTRACT_DENIAL_MISSING_MESSAGE",
    "CONTRACT_DENIAL_MISSING_MODEL",
    "chat_payload",
    "required_capabilities",
    "served_message",
]
