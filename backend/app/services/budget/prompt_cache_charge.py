"""Prompt-cache token split and catalog charge of one usage event.

Two usage conventions reach usage accounting:

- *additional* (Anthropic; the gateway inbound route and ``session_ingest``):
  ``tokens_in`` is the uncached input, cache reads and writes come separately;
- *Bedrock Converse* (the platform's own Bedrock provider): the usage payload
  carries ``inputTokens`` (uncached) plus ``cacheReadInputTokens`` /
  ``cacheWriteInputTokens``, and the prompt count folds all three.

Both are recorded on a ``UsageEvent`` in the additional convention
(``tokens_in`` uncached, cache tokens in ``cache_read_tokens`` /
``cache_creation_tokens``), so token totals mean the same on both paths.

The charge never guesses a rate. With the model row's cache pair, cache tokens are
charged at it. Without it, every path charges cache tokens at the input rate: a
Converse turn and an additional-convention event (``session_ingest``) alike, as
the gateway does, never free. Each outcome is its own ``cost_status``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .model_pricing import ModelPricing

COST_STATUS_PRICED = "priced"
COST_STATUS_PRICED_CACHE_RATES = "priced_cache_rates"
COST_STATUS_PRICED_CACHE_INPUT_RATE = "priced_cache_input_rate"
COST_STATUS_PRICED_CACHE_NOT_CHARGED = "priced_cache_not_charged"


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class PromptTokenSplit:
    uncached_input_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # True for the Bedrock Converse convention: the provider counted the cache
    # tokens as prompt tokens, so without cache rates they are input-rate tokens.
    converse: bool = False

    @property
    def cache_tokens(self) -> int:
        return self.cache_read_tokens + self.cache_write_tokens


def converse_prompt_split(usage: Mapping[str, Any] | None) -> PromptTokenSplit | None:
    """The split of a Bedrock Converse usage payload; ``None`` when it reports no cache tokens."""

    payload = usage or {}
    cache_read = _count(payload.get("cacheReadInputTokens"))
    cache_write = _count(payload.get("cacheWriteInputTokens"))
    if cache_read == 0 and cache_write == 0:
        return None
    return PromptTokenSplit(
        uncached_input_tokens=_count(payload.get("inputTokens")),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        converse=True,
    )


def resolve_prompt_split(
    *,
    prompt_tokens: int,
    usage: Mapping[str, Any] | None,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> PromptTokenSplit:
    """A Converse payload decides on its own; otherwise the cache counts are additional to ``prompt_tokens``."""

    converse = converse_prompt_split(usage)
    if converse is not None:
        return converse
    return PromptTokenSplit(
        uncached_input_tokens=_count(prompt_tokens),
        cache_read_tokens=_count(cache_read_tokens),
        cache_write_tokens=_count(cache_creation_tokens),
    )


def charge_prompt_split(
    pricing: ModelPricing,
    *,
    split: PromptTokenSplit,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[Decimal, str]:
    """Unrounded USD charge and its ``cost_status``.

    ``prompt_tokens`` is the supplied prompt count; it is the charge base whenever no cache rate applies.
    """

    if split.cache_tokens == 0:
        return pricing.charge(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens), COST_STATUS_PRICED
    if pricing.has_cache_rates:
        cost = pricing.charge(
            prompt_tokens=split.uncached_input_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=split.cache_read_tokens,
            cache_creation_tokens=split.cache_write_tokens,
        )
        return cost, COST_STATUS_PRICED_CACHE_RATES
    if split.converse:
        # Converse already folds the cache tokens into the prompt count it was priced at.
        cost = pricing.charge(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return cost, COST_STATUS_PRICED_CACHE_INPUT_RATE
    # Additional convention: the cache tokens come on top of tokens_in. Without a cache pair they are
    # charged at the input rate, like the gateway's inbound route and Bedrock, never left free.
    cost = pricing.charge(prompt_tokens=prompt_tokens + split.cache_tokens, completion_tokens=completion_tokens)
    return cost, COST_STATUS_PRICED_CACHE_INPUT_RATE


__all__ = [
    "COST_STATUS_PRICED",
    "COST_STATUS_PRICED_CACHE_INPUT_RATE",
    "COST_STATUS_PRICED_CACHE_NOT_CHARGED",
    "COST_STATUS_PRICED_CACHE_RATES",
    "PromptTokenSplit",
    "charge_prompt_split",
    "converse_prompt_split",
    "resolve_prompt_split",
]
