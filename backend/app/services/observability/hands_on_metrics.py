"""The hands-on test, measured at the event (never from a database query)."""

from __future__ import annotations

from .metric_types import Counter, _Metric

INVALID = Counter("octryx_hands_on_scenario_invalid_total", "Feature scenarios that failed on the base before the step"
                  " they check (they tested nothing and did not count), by reason", ("reason",))

METRICS: tuple[_Metric, ...] = (INVALID,)


def count_invalid(reason: str) -> None:
    INVALID.inc(reason=reason or "unknown")


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()
