"""Governed cost contract shared by model-catalog sync and usage accounting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Closed cost-source enum. Every governed alias declares exactly one.
COST_SOURCE_CATALOG_PRICING = "catalog_pricing"
COST_SOURCE_GATEWAY_REPORTED = "gateway_reported"
COST_SOURCE_GOVERNED_FREE = "governed_free"
COST_SOURCES = frozenset(
    {COST_SOURCE_CATALOG_PRICING, COST_SOURCE_GATEWAY_REPORTED, COST_SOURCE_GOVERNED_FREE}
)

COST_CONTRACT_PAYLOAD_KEY = "cost_contract"
USAGE_COST_SOURCE_KEY = "cost_source"

# Only this provider-registry *driver key* (never the operator-chosen provider name, which any provider could set)
# may declare a governed cost source: its client builds both payloads from closed, validated fields.
# ``agent/providers/litellm_gateway`` takes its ``PROVIDER_NAME`` from here so the two cannot drift.
GOVERNED_COST_SOURCE_DRIVER = "litellm_gateway"


def governed_cost_source_is_trusted(driver: Any) -> bool:
    return str(driver or "").strip().lower() == GOVERNED_COST_SOURCE_DRIVER


# Fixed sync-validation reasons. They never quote the offending payload.
COST_CONTRACT_DENIAL_MALFORMED = "model_catalog_cost_contract_malformed"
COST_CONTRACT_DENIAL_SOURCE_UNKNOWN = "model_catalog_cost_source_unknown"
COST_CONTRACT_DENIAL_PRICING_INVALID = "model_catalog_cost_pricing_invalid"

COST_STATUS_CATALOG_PRICING = "catalog_pricing"
COST_STATUS_CATALOG_PRICING_UNPRICED = "catalog_pricing_unpriced"
COST_STATUS_GATEWAY_REPORTED = "gateway_reported_cost"
COST_STATUS_GATEWAY_NOT_REPORTED = "gateway_cost_not_reported"
COST_STATUS_GOVERNED_FREE = "governed_free"
COST_STATUS_GOVERNED_FREE_VIOLATION = "governed_free_contract_violation"
COST_STATUS_SOURCE_UNKNOWN = "cost_source_unknown"

_ZERO = Decimal("0")
_COST_CHARACTERS = frozenset("0123456789.eE+-")


def parse_reported_cost(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            cost = float(value)
        except (OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate or any(character not in _COST_CHARACTERS for character in candidate):
            return None
        try:
            cost = float(candidate)
        except ValueError:
            return None
    else:
        return None
    if cost != cost or cost in (float("inf"), float("-inf")) or cost < 0.0:
        return None
    return cost



@dataclass(frozen=True, slots=True)
class GovernedCostResolution:
    cost_source: str
    cost: Decimal | None
    status: str


def resolve_governed_usage_cost(
    usage_payload: Mapping[str, Any],
    *,
    driver: Any = None,
) -> GovernedCostResolution | None:
    if not governed_cost_source_is_trusted(driver):
        return None
    raw_source = usage_payload.get(USAGE_COST_SOURCE_KEY)
    if raw_source is None:
        return None
    source = str(raw_source).strip().lower()
    if source not in COST_SOURCES:
        # Refused rather than quietly re-routed onto the generic pricing path.
        return GovernedCostResolution("", _ZERO, COST_STATUS_SOURCE_UNKNOWN)
    reported = parse_reported_cost(usage_payload.get("cost"))
    if source == COST_SOURCE_GOVERNED_FREE:
        if reported is not None and reported > 0.0:
            # The governance record, not the response, decides the alias is free: a contradiction is recorded at zero,
            # never silently charged.
            return GovernedCostResolution(source, _ZERO, COST_STATUS_GOVERNED_FREE_VIOLATION)
        return GovernedCostResolution(source, _ZERO, COST_STATUS_GOVERNED_FREE)
    if source == COST_SOURCE_GATEWAY_REPORTED:
        if reported is None or reported <= 0.0:
            return GovernedCostResolution(source, _ZERO, COST_STATUS_GATEWAY_NOT_REPORTED)
        return GovernedCostResolution(source, Decimal(str(reported)), COST_STATUS_GATEWAY_REPORTED)
    if reported is not None and reported > 0.0:
        # The adapter already priced this turn from the same catalog contract; re-pricing would double-charge.
        return GovernedCostResolution(source, Decimal(str(reported)), COST_STATUS_CATALOG_PRICING)
    return GovernedCostResolution(source, None, COST_STATUS_CATALOG_PRICING)


__all__ = [
    "COST_CONTRACT_DENIAL_MALFORMED",
    "COST_CONTRACT_DENIAL_PRICING_INVALID",
    "COST_CONTRACT_DENIAL_SOURCE_UNKNOWN",
    "COST_CONTRACT_PAYLOAD_KEY",
    "COST_SOURCES",
    "COST_SOURCE_CATALOG_PRICING",
    "COST_SOURCE_GATEWAY_REPORTED",
    "COST_SOURCE_GOVERNED_FREE",
    "COST_STATUS_CATALOG_PRICING",
    "COST_STATUS_CATALOG_PRICING_UNPRICED",
    "COST_STATUS_GATEWAY_NOT_REPORTED",
    "COST_STATUS_GATEWAY_REPORTED",
    "COST_STATUS_GOVERNED_FREE",
    "COST_STATUS_GOVERNED_FREE_VIOLATION",
    "COST_STATUS_SOURCE_UNKNOWN",
    "GOVERNED_COST_SOURCE_DRIVER",
    "USAGE_COST_SOURCE_KEY",
    "GovernedCostResolution",
    "governed_cost_source_is_trusted",
    "parse_reported_cost",
    "resolve_governed_usage_cost",
]
