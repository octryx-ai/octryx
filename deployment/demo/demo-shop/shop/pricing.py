"""Order totals of the Demo Shop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    """One order line: a product's unit price and how many of it."""

    product: str
    unit_price: float
    quantity: int = 1


def subtotal(lines: list[Line]) -> float:
    """The sum of all lines before any discount."""
    return round(sum(line.unit_price * line.quantity for line in lines), 2)


def order_total(lines: list[Line], discount_percent: float = 0) -> float:
    """The amount to pay: the subtotal less the discount (a percentage of the subtotal, 0 to 100)."""
    if not 0 <= discount_percent <= 100:
        raise ValueError("discount_percent must be between 0 and 100")
    return round(subtotal(lines) - discount_percent, 2)
