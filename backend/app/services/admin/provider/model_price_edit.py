"""Operator edits of a catalog model's prices (USD per million tokens).

The admin model editor may set the input/output prices and the prompt-cache rate pair,
but only while no governed cost source owns the model's price: the next catalog sync
would overwrite a manual edit, so the edit is refused (409) instead.

``None`` means "not priced"; ``0`` is a real price. Cost accounting uses the cache
rates only when both are set (``services/budget/model_pricing``), so an edit that
leaves exactly one of them set is refused (400) rather than silently ignored.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

PRICE_FIELDS = ("pricing_input", "pricing_output", "pricing_cache_read", "pricing_cache_write")
CACHE_RATE_FIELDS = ("pricing_cache_read", "pricing_cache_write")

GOVERNED_PRICE_DETAIL = "Model pricing is owned by its governed cost source and cannot be edited here."
HALF_CACHE_PAIR_DETAIL = "pricing_cache_read and pricing_cache_write are a pair: set both or neither."


def normalize_optional_model_price(value: Any, *, field_name: str) -> float | None:
    if value in ("", None):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a number") from exc
    if price < 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be zero or greater")
    return price


def apply_model_price_edit(model: Any, payload: dict[str, Any]) -> None:
    """Apply the price fields present in ``payload``; validates before writing anything."""

    edited = [field for field in PRICE_FIELDS if field in payload]
    if not edited:
        return
    if model.cost_source:
        raise HTTPException(status_code=409, detail=GOVERNED_PRICE_DETAIL)
    values = {field: normalize_optional_model_price(payload.get(field), field_name=field) for field in edited}
    cache_after = [values.get(field, getattr(model, field)) for field in CACHE_RATE_FIELDS]
    if (cache_after[0] is None) != (cache_after[1] is None):
        raise HTTPException(status_code=400, detail=HALF_CACHE_PAIR_DETAIL)
    for field, value in values.items():
        setattr(model, field, value)


def model_price_snapshot(model: Any) -> dict[str, Any]:
    return {field: getattr(model, field) for field in PRICE_FIELDS} | {"cost_source": model.cost_source}


__all__ = [
    "CACHE_RATE_FIELDS",
    "PRICE_FIELDS",
    "apply_model_price_edit",
    "model_price_snapshot",
    "normalize_optional_model_price",
]
