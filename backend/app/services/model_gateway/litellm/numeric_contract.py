"""Finite-number admission for governed gateway pricing, cost and usage values.

Every positivity rule in this package is a comparison — ``<= 0.0``, ``!= 0.0``,
``< 0`` — and IEEE-754 ``NaN`` fails *all* of them, so a ``NaN`` slips through a
"must be strictly positive" guard unchanged. That matters here because the two
sources of these numbers are both outside this package's control:

- operator configuration (``cost.input_per_million_usd`` and friends), which
  arrives as parsed JSON from the provider row;
- the gateway response body, which ``json.loads`` parses with ``NaN``,
  ``Infinity`` and ``-Infinity`` accepted as literals by default.

A ``NaN`` cost reaching ``compute_usage_event_cost_attribution``
(``services/budget/cost_attribution.py``) is worse than a zero cost: every budget
threshold comparison against it is false, so no guard can ever trip.

A JSON integer also has no width limit, so ``float()`` itself can raise
``OverflowError`` on a large enough literal. That would leave the gateway error
boundary as an unclassified exception instead of a fixed response-contract
denial, so it is converted here too.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["finite_number"]


def finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` if it is not a real number.

    ``None`` is returned for a non-number, a bool (``True`` is not a price), a
    ``NaN``, an infinity, and an integer too large to be a float. Callers treat
    ``None`` as "not reported", which is already a fail-closed state everywhere
    this is used.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None
