"""Cost of one model call: estimates before the call and the attributed cost of a recorded turn."""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..model_gateway.cost_contract import (
    COST_STATUS_CATALOG_PRICING_UNPRICED,
    resolve_governed_usage_cost,
)
from .accounting import _ZERO, UsageCostAttribution, _effective_prompt_tokens, _to_decimal, _usage_int
from .model_pricing import resolve_model_pricing
from .prompt_cache_charge import charge_prompt_split, resolve_prompt_split


def estimate_prompt_tokens(messages: list[dict[str, Any]], *, approx_chars_per_token: int) -> int:
    total_chars = 0
    for message in messages or []:
        role = str(message.get("role") or "")
        total_chars += len(role)
        content = message.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        elif content is not None:
            total_chars += len(str(content))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total_chars += len(str(tool_calls))
    ratio = max(1, int(approx_chars_per_token or 4))
    return max(1, math.ceil(total_chars / ratio))


async def estimate_runtime_cost(
    db: AsyncSession,
    *,
    provider_name: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    # An estimate has no cache split, so prompt tokens are priced at the input rate.
    pricing = await resolve_model_pricing(db, provider_name=provider_name, model_id=model_id)
    if not pricing.priced:
        return _ZERO
    cost = pricing.charge(prompt_tokens=_usage_int(prompt_tokens), completion_tokens=_usage_int(completion_tokens))
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def compute_usage_event_cost(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    usage: dict[str, Any] | None = None,
    driver: str | None = None,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> Decimal:
    attribution = await compute_usage_event_cost_attribution(
        db,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usage=usage,
        driver=driver,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    return attribution.cost


async def compute_usage_event_cost_attribution(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    usage: dict[str, Any] | None = None,
    driver: str | None = None,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> UsageCostAttribution:
    """Attribute one turn's cost."""

    usage_payload = usage or {}
    normalized_provider = str(provider or "").strip()
    normalized_model = str(model or "").strip()
    normalized_tokens_in = _usage_int(tokens_in)
    normalized_tokens_out = _usage_int(tokens_out)
    effective_tokens_in = _effective_prompt_tokens(normalized_tokens_in, usage_payload)
    attribution = partial(
        _attribution, provider=normalized_provider, model=normalized_model, tokens_in=normalized_tokens_in,
        tokens_out=normalized_tokens_out, effective_tokens_in=effective_tokens_in,
    )

    # A governed cost source is resolved first and decides on its own. It is the
    # branch that stops a governed-free or gateway-reported turn from falling
    # through to (possibly stale) catalog pricing, and the one that keeps the
    # recorded source faithful to the contract instead of labelling everything
    # ``provider_reported_cost``. A declaration from any other driver
    # resolves to ``None`` and is attributed by the ungoverned path below.
    governed = resolve_governed_usage_cost(usage_payload, driver=driver)
    if governed is not None and governed.cost is not None:
        return attribution(cost=governed.cost, status=governed.status, cost_source=governed.cost_source)
    explicit_cost = None if governed is not None else usage_payload.get("cost")
    if explicit_cost not in (None, "", "0", 0):
        return attribution(cost=_to_decimal(explicit_cost), status="provider_reported_cost")
    # Only ``catalog_pricing`` reaches here with a governed source: its price is
    # the one model sync persisted from the very same contract.
    cost_source = governed.cost_source if governed is not None else ""
    return await _catalog_attribution(
        db, attribution, provider=normalized_provider, model=normalized_model, cost_source=cost_source,
        usage_payload=usage_payload, effective_tokens_in=effective_tokens_in, tokens_out=normalized_tokens_out,
        cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
    )


async def _catalog_attribution(
    db: AsyncSession,
    attribution: Callable[..., UsageCostAttribution],
    *,
    provider: str,
    model: str,
    cost_source: str,
    usage_payload: dict[str, Any],
    effective_tokens_in: int,
    tokens_out: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> UsageCostAttribution:
    if not hasattr(db, "execute"):
        return attribution(cost=_ZERO, status="cost_unavailable_without_database", cost_source=cost_source)
    pricing = await resolve_model_pricing(db, provider_name=provider, model_id=model)
    if not pricing.priced:
        return attribution(
            cost=_ZERO,
            status=COST_STATUS_CATALOG_PRICING_UNPRICED if cost_source else "missing_pricing",
            cost_source=cost_source,
        )
    split = resolve_prompt_split(
        prompt_tokens=effective_tokens_in,
        usage=usage_payload,
        cache_read_tokens=_usage_int(cache_read_tokens),
        cache_creation_tokens=_usage_int(cache_creation_tokens),
    )
    cost, status = charge_prompt_split(
        pricing, split=split, prompt_tokens=effective_tokens_in, completion_tokens=tokens_out
    )
    return attribution(
        cost=cost,
        status=status,
        cost_source=cost_source,
        pricing_input=pricing.input,
        pricing_output=pricing.output,
    )


def _attribution(
    *,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    effective_tokens_in: int,
    cost: Decimal,
    status: str,
    cost_source: str = "",
    pricing_input: Decimal | None = None,
    pricing_output: Decimal | None = None,
) -> UsageCostAttribution:
    return UsageCostAttribution(
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        effective_tokens_in=effective_tokens_in,
        cost=cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        status=status,
        pricing_input=pricing_input,
        pricing_output=pricing_output,
        cost_source=cost_source,
    )
