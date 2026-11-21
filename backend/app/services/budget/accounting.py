"""Budget accounting types and the number helpers every budget module shares."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_ZERO = Decimal("0")


@dataclass
class BudgetUsageSnapshot:
    requests: int
    tokens: int
    cost: Decimal


@dataclass(frozen=True)
class UsageCostAttribution:
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    effective_tokens_in: int
    cost: Decimal
    status: str
    pricing_input: Decimal | None = None
    pricing_output: Decimal | None = None
    # The governed cost contract the turn ran under, when it declared one.
    cost_source: str = ""


def _to_decimal(value: Any) -> Decimal:
    if value in (None, "", False):
        return _ZERO
    return Decimal(str(value))


def _usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _effective_prompt_tokens(tokens_in: int, usage_payload: dict[str, Any]) -> int:
    bedrock_components = (
        _usage_int(usage_payload.get("inputTokens"))
        + _usage_int(usage_payload.get("cacheReadInputTokens"))
        + _usage_int(usage_payload.get("cacheWriteInputTokens"))
    )
    return max(_usage_int(tokens_in), _usage_int(usage_payload.get("bedrock_total_input_tokens")), bedrock_components)
