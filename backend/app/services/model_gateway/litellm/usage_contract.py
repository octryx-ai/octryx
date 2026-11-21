"""Response usage and cost contract for the governed LiteLLM gateway.

Cost safety is the reason this module exists. ``compute_usage_event_cost_attribution``
(``services/budget/cost_attribution.py``) treats a cost of ``None``/``""``/``"0"``/``0`` as
"not reported" and then falls back to ``LLMModel`` pricing; an alias whose model
row carries no pricing lands on ``status="missing_pricing"`` with ``cost=0``,
which every budget guard happily passes. A gateway call that was really billed
must therefore never leave this module with a zero or unknown cost.

The contract per declared cost source (see ``alias_catalog``):

``catalog_pricing``
    The response must report usable token counts (``prompt_tokens`` > 0,
    ``completion_tokens`` >= 0) and the cost computed from the catalog prices
    must be strictly positive.

``gateway_reported``
    The response must carry a strictly positive numeric cost in ``usage.cost``
    or top-level ``response_cost``. Absent, malformed, negative, and zero
    (including the string ``"0"``) are all refused.

``governed_free``
    The only contract allowed to settle at cost 0. Token counts are still
    required, and a *positive* reported cost contradicts the declaration and is
    refused.

Every refusal is a post-dispatch response-contract violation: the answer was
already billed, so it is discarded rather than retried.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..cost_contract import parse_reported_cost
from .alias_catalog import AliasEntry
from .errors import GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, LiteLLMGatewayError
from .numeric_contract import finite_number

USAGE_DENIAL_NOT_REPORTED = "usage_not_reported"
USAGE_DENIAL_TOKENS_NOT_REPORTED = "usage_tokens_not_reported"
USAGE_DENIAL_PROMPT_TOKENS_NOT_POSITIVE = "usage_prompt_tokens_not_positive"
COST_DENIAL_GATEWAY_NOT_REPORTED = "gateway_cost_not_reported"
COST_DENIAL_GATEWAY_NOT_POSITIVE = "gateway_cost_not_positive"
COST_DENIAL_CATALOG_NOT_POSITIVE = "catalog_cost_not_positive"
COST_DENIAL_FREE_CONTRACT_REPORTED_COST = "free_contract_reported_cost"


def _violation(denial_reason: str) -> LiteLLMGatewayError:
    return LiteLLMGatewayError(
        GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
        denial_reason=denial_reason,
    )


def _token_count(value: Any) -> int | None:
    """Accept only a finite, integral, non-negative token count.

    The finiteness guard comes first because it is the one that keeps an
    exception inside the gateway boundary: ``int(nan)`` raises ``ValueError`` and
    ``int(inf)`` raises ``OverflowError``, and a gateway body may legitimately
    parse to either (``numeric_contract``). Neither may escape this module
    unclassified instead of becoming a response-contract denial.
    """

    count = finite_number(value)
    if count is None or count != float(int(count)) or int(count) < 0:
        return None
    return int(count)


def resolve_reported_tokens(raw_usage: Any) -> tuple[int, int]:
    """Return the validated ``(prompt_tokens, completion_tokens)`` pair.

    A billed call that reports no usable token counts cannot be priced and
    cannot be attributed, so it is refused instead of being recorded as zero.
    """

    if not isinstance(raw_usage, Mapping) or not raw_usage:
        raise _violation(USAGE_DENIAL_NOT_REPORTED) from None
    prompt_tokens = _token_count(raw_usage.get("prompt_tokens"))
    completion_tokens = _token_count(raw_usage.get("completion_tokens"))
    if prompt_tokens is None or completion_tokens is None:
        raise _violation(USAGE_DENIAL_TOKENS_NOT_REPORTED) from None
    if prompt_tokens <= 0:
        raise _violation(USAGE_DENIAL_PROMPT_TOKENS_NOT_POSITIVE) from None
    return prompt_tokens, completion_tokens


def _catalog_cost(entry: AliasEntry, *, prompt_tokens: int, completion_tokens: int) -> float:
    cost = (
        prompt_tokens * (entry.cost.input_per_million_usd or 0.0)
        + completion_tokens * (entry.cost.output_per_million_usd or 0.0)
    ) / 1_000_000
    # Admission already requires finite prices and validated token counts, so this
    # is the second, independent guard: a product of two admitted values can still
    # overflow to infinity, and an infinite cost passes every ``<= 0.0`` check.
    if finite_number(cost) is None or cost <= 0.0:
        raise _violation(COST_DENIAL_CATALOG_NOT_POSITIVE) from None
    return cost


def _gateway_cost(body: Mapping[str, Any], raw_usage: Mapping[str, Any]) -> float:
    reported = parse_reported_cost(raw_usage.get("cost"))
    if reported is None:
        reported = parse_reported_cost(body.get("response_cost"))
    if reported is None:
        raise _violation(COST_DENIAL_GATEWAY_NOT_REPORTED) from None
    if reported <= 0.0:
        # A reported zero is indistinguishable from "unknown" once it reaches
        # the budget attribution, so it is refused rather than trusted.
        raise _violation(COST_DENIAL_GATEWAY_NOT_POSITIVE) from None
    return reported


def _governed_free_cost(body: Mapping[str, Any], raw_usage: Mapping[str, Any]) -> float:
    for candidate in (raw_usage.get("cost"), body.get("response_cost")):
        reported = parse_reported_cost(candidate)
        if reported is not None and reported > 0.0:
            raise _violation(COST_DENIAL_FREE_CONTRACT_REPORTED_COST) from None
    return 0.0


def resolve_usage_payload(
    entry: AliasEntry,
    body: Mapping[str, Any],
    raw_usage: Any,
) -> dict[str, Any]:
    """Build the validated usage payload for one served gateway response."""

    # Raises unless ``raw_usage`` is a non-empty mapping with usable counts.
    prompt_tokens, completion_tokens = resolve_reported_tokens(raw_usage)
    usage: Mapping[str, Any] = raw_usage
    if entry.cost.gateway_reported:
        cost = _gateway_cost(body, usage)
    elif entry.cost.governed_free:
        cost = _governed_free_cost(body, usage)
    else:
        cost = _catalog_cost(entry, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "cost_source": entry.cost.source,
    }


__all__ = [
    "COST_DENIAL_CATALOG_NOT_POSITIVE",
    "COST_DENIAL_FREE_CONTRACT_REPORTED_COST",
    "COST_DENIAL_GATEWAY_NOT_POSITIVE",
    "COST_DENIAL_GATEWAY_NOT_REPORTED",
    "USAGE_DENIAL_NOT_REPORTED",
    "USAGE_DENIAL_PROMPT_TOKENS_NOT_POSITIVE",
    "USAGE_DENIAL_TOKENS_NOT_REPORTED",
    "resolve_reported_tokens",
    "resolve_usage_payload",
]
