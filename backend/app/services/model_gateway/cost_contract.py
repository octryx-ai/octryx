"""Governed cost contract shared by model-catalog sync and usage accounting.

A gateway alias declares *who owns its price*. That declaration is the single
authority for both persisted catalog pricing and per-turn cost attribution, so
the two can never disagree:

``catalog_pricing``
    Octryx owns the price. The synchronized per-token prices are
    persisted and are the fallback when a turn reports no cost of its own.

``gateway_reported``
    The gateway owns the price. Any persisted catalog price for that model could
    only be stale, so sync *clears* it and attribution never reads it: a turn
    without a positive reported cost settles at an explicit
    ``gateway_cost_not_reported`` status instead of at an old number.

``governed_free``
    A named governance record owns the price, and it is zero. Sync persists that
    audited zero rather than leaving the previous price in place.

This module holds the enum, the trust rule, the narrow reported-cost parser and
the usage-accounting resolution; the catalog-sync decision lives in
:mod:`.cost_contract_pricing`. It deliberately knows nothing about HTTP,
providers, or the database: ``services/admin/provider`` applies the sync
decision and ``services/budget`` applies the accounting resolution.

A payload that declares no cost contract resolves to ``None`` everywhere here,
which is how every non-gateway provider keeps its existing behaviour.

Trust boundary: a declared cost source is only *believed* when the governed
gateway driver produced it — a usage payload when that driver served the turn, a
``cost_contract`` when that driver produced the synchronized catalog. Every other
driver hands back whatever its upstream endpoint sent, so nothing it declares is
read here. See :data:`GOVERNED_COST_SOURCE_DRIVER`.
"""

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

# Key the model-catalog payload carries the governed contract under.
COST_CONTRACT_PAYLOAD_KEY = "cost_contract"
# Key the per-turn usage payload carries the governed source under.
USAGE_COST_SOURCE_KEY = "cost_source"

# The only provider driver whose payloads may declare a governed cost source —
# ``cost_source`` in a served usage payload, and ``cost_contract`` in a
# synchronized model catalog. This is the *driver key* from the provider registry
# — the identity that decides which client class serves a turn and builds a
# catalog — and never the operator-chosen provider name, which any provider could
# set to "litellm_gateway". Only ``LiteLLMGatewayClient`` runs under this key, and
# it builds both payloads from closed sets of validated fields
# (``litellm/usage_contract``, ``litellm/alias_catalog``), so an upstream response
# can neither smuggle a declaration through it nor make one from another driver.
# ``agent/providers/litellm_gateway`` takes its ``PROVIDER_NAME`` from this
# constant, so the two cannot drift apart.
GOVERNED_COST_SOURCE_DRIVER = "litellm_gateway"


def governed_cost_source_is_trusted(driver: Any) -> bool:
    """Whether a turn or a catalog entry served by ``driver`` may declare a governed cost source.

    Both ends of the contract ask this, and both ask it about the *driver key*
    from the provider registry, never about a provider name or a payload field.
    """

    return str(driver or "").strip().lower() == GOVERNED_COST_SOURCE_DRIVER


# Fixed sync-validation reasons. They never quote the offending payload.
COST_CONTRACT_DENIAL_MALFORMED = "model_catalog_cost_contract_malformed"
COST_CONTRACT_DENIAL_SOURCE_UNKNOWN = "model_catalog_cost_source_unknown"
COST_CONTRACT_DENIAL_PRICING_INVALID = "model_catalog_cost_pricing_invalid"

# Closed accounting statuses.
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
    """Parse a reported cost from a narrow numeric shape; never retain the raw value.

    Returns ``None`` for anything that is not a finite, non-negative number,
    including booleans and numeric-looking values outside that shape. The
    character allowlist keeps an arbitrary provider string from reaching
    ``float`` — and from reaching a trace or an error through it.
    """

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
    """The accounting outcome for one turn served under a governed cost source.

    ``cost is None`` means "price this from the synchronized catalog prices" and
    is only ever produced for ``catalog_pricing``; every other source settles
    here, with no database read and no catalog fallback.
    """

    cost_source: str
    cost: Decimal | None
    status: str


def resolve_governed_usage_cost(
    usage_payload: Mapping[str, Any],
    *,
    driver: Any = None,
) -> GovernedCostResolution | None:
    """Resolve a turn's cost from its declared cost source, or ``None`` if ungoverned.

    ``driver`` is the serving provider driver key. A declaration made by
    anything other than the governed gateway driver is not a governed turn at
    all: it is discarded here and never reaches pricing, an accounting status or
    a persisted ``cost_source``. Whatever the payload claims, such a turn is
    attributed by the ungoverned path.
    """

    if not governed_cost_source_is_trusted(driver):
        return None
    raw_source = usage_payload.get(USAGE_COST_SOURCE_KEY)
    if raw_source is None:
        return None
    source = str(raw_source).strip().lower()
    if source not in COST_SOURCES:
        # A payload that declares a source outside the closed enum is refused
        # rather than quietly re-routed onto the generic pricing path.
        return GovernedCostResolution("", _ZERO, COST_STATUS_SOURCE_UNKNOWN)
    reported = parse_reported_cost(usage_payload.get("cost"))
    if source == COST_SOURCE_GOVERNED_FREE:
        if reported is not None and reported > 0.0:
            # The governance record, not the response, decides that this alias is
            # free. The gateway client already discards such a response;
            # if one ever reaches here it is recorded as a contradiction at zero
            # instead of silently becoming a charge.
            return GovernedCostResolution(source, _ZERO, COST_STATUS_GOVERNED_FREE_VIOLATION)
        return GovernedCostResolution(source, _ZERO, COST_STATUS_GOVERNED_FREE)
    if source == COST_SOURCE_GATEWAY_REPORTED:
        if reported is None or reported <= 0.0:
            return GovernedCostResolution(source, _ZERO, COST_STATUS_GATEWAY_NOT_REPORTED)
        return GovernedCostResolution(source, Decimal(str(reported)), COST_STATUS_GATEWAY_REPORTED)
    if reported is not None and reported > 0.0:
        # The dispatching adapter already priced this turn from the same catalog
        # contract the sync persisted. Re-pricing it from the model row would be
        # a second, divergent charge for one call.
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
