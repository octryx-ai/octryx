"""What one model call on a seat would have cost through the API, at today's list price.

A seat call costs the platform nothing (the subscription is paid elsewhere), but the platform shows
what the same call would cost through the API, so a person can see "what would this cost without the subscription".
It is the call's **API equivalent**, always shown apart from the real API cost and never added to it.

- The price is the dated list price (``list_prices.json``), per call, at the tier the call's prompt falls in
  (Haiku 5.5 above 100k, GPT-6 above 272k prompt tokens). Never the model catalog: the catalog holds what this
  install pays, the list price is what the API would charge.
- Token keys are Anthropic's: ``input_tokens`` without the cached part, cache reads and writes on top. A 1-hour
  cache write is priced at the table's 1-hour rate when it has one.
- A model without a list price gets ``None`` — never an estimate and never a similar model's price; the display
  counts such calls as "no list price".
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .list_prices import call_list_price

_ONE_MILLION = Decimal("1000000")


def _tokens(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _rate(value: float | None) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def one_hour_writes(usage: Mapping[str, Any]) -> int:
    """The call's 1-hour cache writes: the flat launcher field, else Claude's ``cache_creation`` detail."""
    flat = _tokens(usage.get("cache_creation_1h_input_tokens"))
    if flat:
        return flat
    detail = usage.get("cache_creation")
    return _tokens(detail.get("ephemeral_1h_input_tokens")) if isinstance(detail, Mapping) else 0


def api_equivalent_usd(model: str, usage: Mapping[str, Any]) -> Decimal | None:
    """The list-price USD of one call's ``usage``, unrounded; ``None`` when the model has no list price."""
    uncached = _tokens(usage.get("input_tokens"))
    reads = _tokens(usage.get("cache_read_input_tokens"))
    writes = _tokens(usage.get("cache_creation_input_tokens"))
    price = call_list_price(model, prompt_tokens=uncached + reads + writes)
    if price is None:
        return None
    one_hour = min(one_hour_writes(usage), writes) if price.cache_write_1h is not None else 0
    # A table without a cache rate charges the cached tokens at the input rate, like the gateway's own pricing.
    read_rate = _rate(price.cache_read if price.cache_read is not None else price.input)
    write_rate = _rate(price.cache_write if price.cache_write is not None else price.input)
    total = (Decimal(uncached) * _rate(price.input) + Decimal(reads) * read_rate
             + Decimal(writes - one_hour) * write_rate + Decimal(one_hour) * _rate(price.cache_write_1h)
             + Decimal(_tokens(usage.get("output_tokens"))) * _rate(price.output))
    return total / _ONE_MILLION


def stored(value: Decimal | None) -> Decimal | None:
    """The value as the ``Numeric(12, 6)`` column stores it."""
    return None if value is None else value.quantize(Decimal("0.000001"))


__all__ = ["api_equivalent_usd", "one_hour_writes", "stored"]
