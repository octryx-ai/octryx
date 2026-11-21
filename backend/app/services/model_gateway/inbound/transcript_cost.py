"""Cost of one inbound model call under the alias' governed cost contract (``transcript``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..cost_contract import GOVERNED_COST_SOURCE_DRIVER, resolve_governed_usage_cost
from ..litellm.alias_catalog import AliasEntry
from ..litellm.errors import LiteLLMGatewayError
from ..litellm.usage_contract import resolve_usage_payload


@dataclass(frozen=True, slots=True)
class UsageCost:
    cost: Decimal
    cost_source: str
    cost_status: str


def _cache_aware_catalog_cost(entry: AliasEntry, usage: Mapping[str, int]) -> float | None:
    contract = entry.cost
    if contract.gateway_reported or contract.governed_free or contract.cache_read_per_million_usd is None:
        return None
    prompt = sum(int(usage.get(key) or 0)
                 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    cost = contract.long_context_multiplier(prompt) * (
        int(usage.get("input_tokens") or 0) * (contract.input_per_million_usd or 0.0)
        + int(usage.get("cache_creation_input_tokens") or 0) * (contract.cache_write_per_million_usd or 0.0)
        + int(usage.get("cache_read_input_tokens") or 0) * contract.cache_read_per_million_usd
        + int(usage.get("output_tokens") or 0) * (contract.output_per_million_usd or 0.0)
    ) / 1_000_000
    return cost if 0.0 < cost < float("inf") else None


def usage_cost(entry: AliasEntry, usage: Mapping[str, int]) -> UsageCost:
    prompt_tokens = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    raw_usage = {"prompt_tokens": prompt_tokens, "completion_tokens": int(usage.get("output_tokens") or 0)}
    try:
        payload = resolve_usage_payload(entry, {}, raw_usage)
    except LiteLLMGatewayError as exc:
        return UsageCost(Decimal("0"), entry.cost.source, exc.denial_reason or exc.gateway_state)
    cache_cost = _cache_aware_catalog_cost(entry, usage)
    if cache_cost is not None:
        # Same validated payload, priced per token class: cache reads and writes at the
        # alias' declared cache rates instead of the input rate.
        payload = {**payload, "cost": cache_cost}
    governed = resolve_governed_usage_cost(payload, driver=GOVERNED_COST_SOURCE_DRIVER)
    if governed is None or governed.cost is None:
        return UsageCost(Decimal("0"), entry.cost.source, governed.status if governed else "cost_source_unknown")
    return UsageCost(governed.cost, governed.cost_source, governed.status)


__all__ = ["UsageCost", "usage_cost"]
