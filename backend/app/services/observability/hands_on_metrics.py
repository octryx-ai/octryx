"""The hands-on test, measured at the event (never from a database query):

- ``octryx_hands_on_scenario_invalid_total{reason}``: a platform-written feature scenario that failed on the base at
  the same step, before the step it checks; it tested nothing and did not count (``data_lost_after_restart``,
  ``setup_fails_on_base``). How often the scenario writer misses, and a source for From Correction to Check.

Imports only ``metric_types`` (``agent_metrics`` imports this module early).
"""

from __future__ import annotations

from .metric_types import Counter, _Metric

INVALID = Counter("octryx_hands_on_scenario_invalid_total", "Feature scenarios that failed on the base before the step"
                  " they check (they tested nothing and did not count), by reason", ("reason",))

METRICS: tuple[_Metric, ...] = (INVALID,)


def count_invalid(reason: str) -> None:
    INVALID.inc(reason=reason or "unknown")


def reset() -> None:
    """Tests: start empty."""
    for metric in METRICS:
        metric.series.clear()
