"""How a usage event's cost counts (observability O1/O3).

``usage_events.cost_status`` is the accounting outcome of every model call. Observability groups it into three
states: ``priced`` (the cost is real), ``unpriced`` (platform-billed, but no price was known, so the cost is 0 and
no cost cap can stop it) and ``not_billed`` (a seat or device subscription pays, not the platform).
"""

from __future__ import annotations

from sqlalchemy import case, or_

from ...models import UsageEvent

COST_PRICED = "priced"
COST_UNPRICED = "unpriced"
COST_NOT_BILLED = "not_billed"

PRICED_STATUSES = ("priced", "catalog_pricing", "gateway_reported_cost", "governed_free")
NOT_BILLED_STATUSES = ("not_billed_to_platform",)
UNPRICED_STATUSES = (
    "missing_pricing",
    "catalog_pricing_unpriced",
    "gateway_cost_not_reported",
    "cost_source_unknown",
    "governed_free_contract_violation",
)


def cost_state_expression():
    """SQL expression: the cost state of a ``usage_events`` row (an unknown status counts by its amount)."""
    return case(
        (UsageEvent.cost_status.in_(NOT_BILLED_STATUSES), COST_NOT_BILLED),
        (UsageEvent.cost_status.in_(PRICED_STATUSES), COST_PRICED),
        (or_(UsageEvent.cost_status.in_(UNPRICED_STATUSES), UsageEvent.cost <= 0), COST_UNPRICED),
        else_=COST_PRICED,
    )


def cost_state(status: str | None, cost: float) -> str:
    if status in NOT_BILLED_STATUSES:
        return COST_NOT_BILLED
    if status in PRICED_STATUSES:
        return COST_PRICED
    if status in UNPRICED_STATUSES or cost <= 0:
        return COST_UNPRICED
    return COST_PRICED


def run_cost_state(states: set[str]) -> str | None:
    """A run's cost label: unpriced wins (the shown cost is too low), then priced, then not billed."""
    for state in (COST_UNPRICED, COST_PRICED, COST_NOT_BILLED):
        if state in states:
            return state
    return None
