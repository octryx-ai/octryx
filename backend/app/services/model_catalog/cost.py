"""The Cost tab of a catalog model.

- **Gateway model**: the price authority is the alias cost contract (``alias_catalog``: ``catalog_pricing`` with two
  strictly positive rates and an optional strictly positive cache pair, or ``gateway_reported`` /
  ``governed_free`` naming their contract record). The catalog writes the contract into the alias and mirrors
  the rates onto the row, with ``cost_source`` = the contract source, so there is no second price.
- **Any other model**: ``admin/provider/model_price_edit`` decides: refused while a governed cost source owns the
  price, cache rates only as a pair.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from ...models import LLMModel, LLMProvider
from ..admin.provider.model_price_edit import apply_model_price_edit
from ..model_gateway.cost_contract import COST_SOURCE_CATALOG_PRICING, COST_SOURCES
from .alias_mirror import write_alias_cost
from .contract import ERROR_COST_GOVERNED, ERROR_COST_INVALID, ModelCatalogError

COST_FIELDS = frozenset(
    {"cost_source", "pricing_input", "pricing_output", "pricing_cache_read", "pricing_cache_write",
     "contract_reference", "long_context_threshold_tokens", "long_context_factor"}
)
MAX_CONTRACT_REFERENCE_CHARS = 200


def _rate(value: Any, *, required: bool) -> float | None:
    if value is None or value == "":
        if required:
            raise ModelCatalogError(ERROR_COST_INVALID)
        return None
    if isinstance(value, bool):
        raise ModelCatalogError(ERROR_COST_INVALID)
    try:
        rate = float(value)
    except (TypeError, ValueError):
        raise ModelCatalogError(ERROR_COST_INVALID) from None
    if not math.isfinite(rate) or rate <= 0:
        raise ModelCatalogError(ERROR_COST_INVALID)
    return rate


def gateway_cost_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """The alias ``cost`` block for a submitted Cost tab; raises ``ModelCatalogError`` like the admission would."""
    source = str(payload.get("cost_source") or "").strip().lower()
    if source not in COST_SOURCES:
        raise ModelCatalogError(ERROR_COST_INVALID)
    if source != COST_SOURCE_CATALOG_PRICING:
        reference = str(payload.get("contract_reference") or "").strip()
        if not reference or len(reference) > MAX_CONTRACT_REFERENCE_CHARS:
            raise ModelCatalogError(ERROR_COST_INVALID)
        return {"source": source, "contract_reference": reference}
    contract: dict[str, Any] = {
        "source": source,
        "input_per_million_usd": _rate(payload.get("pricing_input"), required=True),
        "output_per_million_usd": _rate(payload.get("pricing_output"), required=True),
    }
    cache_read = _rate(payload.get("pricing_cache_read"), required=False)
    cache_write = _rate(payload.get("pricing_cache_write"), required=False)
    if (cache_read is None) != (cache_write is None):
        raise ModelCatalogError(ERROR_COST_INVALID)
    if cache_read is not None:
        contract["cache_read_per_million_usd"] = cache_read
        contract["cache_write_per_million_usd"] = cache_write
    threshold, factor = payload.get("long_context_threshold_tokens"), payload.get("long_context_factor")
    if threshold is not None or factor is not None:
        factor_rate = _rate(factor, required=True)
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0 or factor_rate < 1.0:
            raise ModelCatalogError(ERROR_COST_INVALID)
        contract["long_context_threshold_tokens"] = threshold
        contract["long_context_factor"] = factor_rate
    return contract


def apply_cost(provider: LLMProvider, model: LLMModel, payload: dict[str, Any], *, gateway: bool) -> None:
    unknown = set(payload) - COST_FIELDS
    if unknown:
        raise ModelCatalogError(ERROR_COST_INVALID)
    if gateway:
        contract = gateway_cost_contract(payload)
        write_alias_cost(provider, model.model_id, contract)
        model.cost_source = contract["source"]
        model.pricing_input = contract.get("input_per_million_usd")
        model.pricing_output = contract.get("output_per_million_usd")
        model.pricing_cache_read = contract.get("cache_read_per_million_usd")
        model.pricing_cache_write = contract.get("cache_write_per_million_usd")
        return
    prices = {key: value for key, value in payload.items() if key.startswith("pricing_")}
    try:
        apply_model_price_edit(model, prices)
    except HTTPException as error:
        code = ERROR_COST_GOVERNED if error.status_code == 409 else ERROR_COST_INVALID
        raise ModelCatalogError(code, status=error.status_code, detail=str(error.detail)) from None


__all__ = ["COST_FIELDS", "apply_cost", "gateway_cost_contract"]
