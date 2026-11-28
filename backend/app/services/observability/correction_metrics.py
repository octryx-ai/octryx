"""Corrections of agents' work (From Correction to Check), counted in process when a capture commits."""

from __future__ import annotations

from .metric_types import Counter

CAPTURED = Counter("octryx_corrections_captured_total", "Corrections of agents' work kept under a signature, by "
                   "source", ("source",))
OVER_THRESHOLD = Counter("octryx_check_signatures_over_threshold_total", "Correction signatures whose repeats "
                         "reached the Workspace's threshold (counted once each), by the check kind they hint at",
                         ("kind_hint",))
METRICS = (CAPTURED, OVER_THRESHOLD)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()


__all__ = ["CAPTURED", "METRICS", "OVER_THRESHOLD", "reset"]
