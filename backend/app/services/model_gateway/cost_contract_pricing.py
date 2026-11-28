"""Catalog-sync side of the governed cost contract: what one synchronized catalog entry writes to its model row."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .cost_contract import (
    COST_CONTRACT_DENIAL_MALFORMED,
    COST_CONTRACT_DENIAL_PRICING_INVALID,
    COST_CONTRACT_DENIAL_SOURCE_UNKNOWN,
    COST_CONTRACT_PAYLOAD_KEY,
    COST_SOURCE_CATALOG_PRICING,
    COST_SOURCE_GATEWAY_REPORTED,
    COST_SOURCE_GOVERNED_FREE,
    COST_SOURCES,
    governed_cost_source_is_trusted,
)


# Finite and strictly positive: a zero rate bills tokens at nothing while claiming catalog_pricing, and NaN or infinity
# pass a naive > 0 test and poison every cost and budget guard. A free model declares governed_free, which is audited.
def _billable_rate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        rate = float(value)
    except (OverflowError, ValueError):
        return None
    if rate != rate or rate in (float("inf"), float("-inf")) or rate <= 0.0:
        return None
    return rate


# An authoritative update assigns every field, None included, so a mode change clears what the previous mode stored; the
# prompt-cache pair is set only by a governed catalog_pricing contract and cleared when it stops declaring it.
@dataclass(frozen=True, slots=True)
class ModelPricingUpdate:
    pricing_input: float | None
    pricing_output: float | None
    cost_source: str | None
    authoritative: bool
    pricing_cache_read: float | None = None
    pricing_cache_write: float | None = None


# The cache pair is published only when declared: its absence is what clears stored cache rates on the next sync.
def build_cost_contract_payload(
    *,
    source: str,
    input_per_million_usd: float | None = None,
    output_per_million_usd: float | None = None,
    cache_read_per_million_usd: float | None = None,
    cache_write_per_million_usd: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": source}
    if source == COST_SOURCE_CATALOG_PRICING:
        payload["input_per_million_usd"] = input_per_million_usd
        payload["output_per_million_usd"] = output_per_million_usd
        if cache_read_per_million_usd is not None or cache_write_per_million_usd is not None:
            payload["cache_read_per_million_usd"] = cache_read_per_million_usd
            payload["cache_write_per_million_usd"] = cache_write_per_million_usd
    return payload


# Both cache rates or neither, each billable as the alias catalog admits it; a half pair fails the sync instead of
# storing a partial price.
def _cache_rate_pair(raw: Mapping[str, Any]) -> tuple[float | None, float | None]:
    raw_read = raw.get("cache_read_per_million_usd")
    raw_write = raw.get("cache_write_per_million_usd")
    if raw_read is None and raw_write is None:
        return None, None
    cache_read, cache_write = _billable_rate(raw_read), _billable_rate(raw_write)
    if cache_read is None or cache_write is None:
        raise ValueError(COST_CONTRACT_DENIAL_PRICING_INVALID)
    return cache_read, cache_write


# A malformed contract fails catalog validation: a skip would keep the previous pricing mode's stored prices.
def resolve_cost_contract_pricing(raw: Any) -> ModelPricingUpdate | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(COST_CONTRACT_DENIAL_MALFORMED)
    source = str(raw.get("source") or "").strip().lower()
    if source not in COST_SOURCES:
        raise ValueError(COST_CONTRACT_DENIAL_SOURCE_UNKNOWN)
    if source == COST_SOURCE_GOVERNED_FREE:
        # An audited zero, not an unknown price: persisted so a later reader can
        # tell "free by governance" from "never priced".
        return ModelPricingUpdate(0.0, 0.0, source, True)
    if source == COST_SOURCE_GATEWAY_REPORTED:
        # Upstream owns the price; any persisted number could only be stale.
        return ModelPricingUpdate(None, None, source, True)
    input_price = _billable_rate(raw.get("input_per_million_usd"))
    output_price = _billable_rate(raw.get("output_per_million_usd"))
    if input_price is None or output_price is None:
        # Each required rate on its own, not their sum: a positive input rate
        # must not admit a zero (or non-finite) output rate alongside it.
        raise ValueError(COST_CONTRACT_DENIAL_PRICING_INVALID)
    cache_read, cache_write = _cache_rate_pair(raw)
    return ModelPricingUpdate(input_price, output_price, source, True, cache_read, cache_write)


# Read for every provider without a governed contract; a zero-like value counts as not sent.
def _plain_per_token_price(raw_pricing: Any, key: str) -> float | None:
    if not isinstance(raw_pricing, Mapping):
        return None
    value = raw_pricing.get(key)
    if value in (None, "0", "", 0):
        return None
    try:
        return float(value) * 1_000_000
    except (TypeError, ValueError):
        return None


# Only the governed driver's catalog may declare a cost_contract (any other upstream could clear a price or stamp
# governed_free); without one, plain pricing applies non-authoritatively, so operator-set prices of other providers are
# never cleared.
def resolve_model_pricing_update(
    model_payload: Mapping[str, Any],
    *,
    driver: Any = None,
) -> ModelPricingUpdate:
    if governed_cost_source_is_trusted(driver):
        governed = resolve_cost_contract_pricing(model_payload.get(COST_CONTRACT_PAYLOAD_KEY))
        if governed is not None:
            return governed
    raw_pricing = model_payload.get("pricing")
    return ModelPricingUpdate(
        _plain_per_token_price(raw_pricing, "prompt"),
        _plain_per_token_price(raw_pricing, "completion"),
        None,
        False,
    )


def apply_model_pricing_update(model: Any, update: ModelPricingUpdate) -> None:
    if update.authoritative:
        # Assigns ``None`` too: clearing the previous mode's price is the point.
        model.pricing_input = update.pricing_input
        model.pricing_output = update.pricing_output
        model.pricing_cache_read = update.pricing_cache_read
        model.pricing_cache_write = update.pricing_cache_write
        model.cost_source = update.cost_source
        return
    # The plain per-token block never carries cache rates, so it leaves them alone.
    if update.pricing_input is not None:
        model.pricing_input = update.pricing_input
    if update.pricing_output is not None:
        model.pricing_output = update.pricing_output


__all__ = [
    "ModelPricingUpdate",
    "apply_model_pricing_update",
    "build_cost_contract_payload",
    "resolve_cost_contract_pricing",
    "resolve_model_pricing_update",
]
