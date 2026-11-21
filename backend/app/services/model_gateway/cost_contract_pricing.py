"""Catalog-sync side of the governed cost contract (:mod:`.cost_contract`).

Decides what one synchronized model-catalog entry writes to its model row: a
governed ``cost_contract`` block is authoritative (it may clear a stale price),
the plain per-token ``pricing`` block is not. Only the governed gateway driver's
catalog may declare a contract; see :func:`resolve_model_pricing_update`.
"""

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


def _billable_rate(value: Any) -> float | None:
    """A per-token rate a governed catalog price may actually be charged at.

    Every required rate must be a finite, strictly positive real number. Zero is
    refused because a rate of zero silently bills those tokens at nothing while
    still claiming ``catalog_pricing``; NaN and infinity are refused because both
    survive a naive ``> 0`` test and would then propagate into a computed cost, a
    budget guard and a persisted charge (NaN compares false against every limit,
    infinity exhausts every limit at once). A model that genuinely costs nothing
    declares ``governed_free``, which is audited.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        rate = float(value)
    except (OverflowError, ValueError):
        return None
    if rate != rate or rate in (float("inf"), float("-inf")) or rate <= 0.0:
        return None
    return rate


@dataclass(frozen=True, slots=True)
class ModelPricingUpdate:
    """What one synchronized catalog entry says about a model row's pricing.

    ``authoritative`` decides the write: an authoritative update
    assigns every pricing field, including ``None``, so a mode transition clears
    what the previous mode persisted. A non-authoritative update writes only
    the values the provider actually sent.

    The prompt-cache pair is optional and only ever set by a governed
    ``catalog_pricing`` contract; an authoritative update without it clears the
    pair, so a contract that stops declaring cache rates cannot leave old ones.
    """

    pricing_input: float | None
    pricing_output: float | None
    cost_source: str | None
    authoritative: bool
    pricing_cache_read: float | None = None
    pricing_cache_write: float | None = None


def build_cost_contract_payload(
    *,
    source: str,
    input_per_million_usd: float | None = None,
    output_per_million_usd: float | None = None,
    cache_read_per_million_usd: float | None = None,
    cache_write_per_million_usd: float | None = None,
) -> dict[str, Any]:
    """Build the closed ``cost_contract`` block a model-catalog entry publishes.

    The prompt-cache pair is published only when the alias declares it; its
    absence is what makes a later sync clear previously persisted cache rates.
    """

    payload: dict[str, Any] = {"source": source}
    if source == COST_SOURCE_CATALOG_PRICING:
        payload["input_per_million_usd"] = input_per_million_usd
        payload["output_per_million_usd"] = output_per_million_usd
        if cache_read_per_million_usd is not None or cache_write_per_million_usd is not None:
            payload["cache_read_per_million_usd"] = cache_read_per_million_usd
            payload["cache_write_per_million_usd"] = cache_write_per_million_usd
    return payload


def _cache_rate_pair(raw: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """The optional prompt-cache pair of a ``catalog_pricing`` contract.

    Both rates or neither, and a present rate must be billable — the same rule
    the alias catalog admits (``litellm/alias_catalog``). A half pair or an
    unusable rate fails the sync instead of persisting a partial cache price.
    """

    raw_read = raw.get("cache_read_per_million_usd")
    raw_write = raw.get("cache_write_per_million_usd")
    if raw_read is None and raw_write is None:
        return None, None
    cache_read, cache_write = _billable_rate(raw_read), _billable_rate(raw_write)
    if cache_read is None or cache_write is None:
        raise ValueError(COST_CONTRACT_DENIAL_PRICING_INVALID)
    return cache_read, cache_write


def resolve_cost_contract_pricing(raw: Any) -> ModelPricingUpdate | None:
    """Resolve a governed ``cost_contract`` block into an authoritative pricing update.

    ``None`` means the entry declares no governed contract. A malformed one is a
    catalog-validation failure rather than a silent skip: a skip would leave the
    stored prices of the previous pricing mode in place instead of replacing them.
    """

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


def _plain_per_token_price(raw_pricing: Any, key: str) -> float | None:
    """The plain per-token ``pricing`` block, converted to per-million USD.

    Every provider that does not publish a governed cost contract is read this
    way, including treating a zero-like value as "not sent".
    """

    if not isinstance(raw_pricing, Mapping):
        return None
    value = raw_pricing.get(key)
    if value in (None, "0", "", 0):
        return None
    try:
        return float(value) * 1_000_000
    except (TypeError, ValueError):
        return None


def resolve_model_pricing_update(
    model_payload: Mapping[str, Any],
    *,
    driver: Any = None,
) -> ModelPricingUpdate:
    """Decide what one synchronized catalog entry writes to its model row.

    ``driver`` is the provider-registry driver key of the provider being synced —
    the server-owned identity that decides which client class produced this
    catalog. Only the governed gateway driver's catalog may declare a
    ``cost_contract``: every other driver returns whatever its upstream ``/models``
    endpoint sent, so believing a ``cost_contract`` there would let an upstream
    response clear a model's price or stamp it ``governed_free``. For an
    untrusted driver the key is not read at all.

    A governed ``cost_contract`` wins and is authoritative. Otherwise the plain
    ``pricing`` block applies non-authoritatively, which is what keeps
    non-gateway providers from having their operator-set prices cleared by a
    sync that simply did not mention them.
    """

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
    """Write a pricing update onto an ``LLMModel`` row."""

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
