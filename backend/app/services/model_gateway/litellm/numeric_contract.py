"""Finite-number admission for governed gateway pricing, cost and usage values."""

from __future__ import annotations

import math
from typing import Any

__all__ = ["finite_number"]


# NaN fails every comparison, so it would slip through a must-be-positive guard and silence every budget threshold; None
# (a non-number, a bool, NaN, infinity, an integer too large for a float) reads as not reported, which fails closed.
def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None
