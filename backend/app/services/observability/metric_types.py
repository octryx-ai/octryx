"""Prometheus metric types kept in process memory (``octryx_*``): counters and histograms with bounded labels."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

MAX_SERIES = 500
OTHER = "other"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _number(value: float) -> str:
    if value == math.inf:
        return "+Inf"
    return str(int(value)) if float(value).is_integer() else repr(float(value))


class _Metric:
    kind = ""

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...], max_series: int = MAX_SERIES) -> None:
        self.name, self.help, self.labels, self.max_series = name, help_text, labels, max_series
        self.series: dict[tuple[str, ...], Any] = {}

    def _key(self, values: dict[str, Any]) -> tuple[str, ...]:
        key = tuple(str(values.get(label) or "unknown")[:200] for label in self.labels)
        if key not in self.series and len(self.series) >= self.max_series:
            return tuple(OTHER for _ in self.labels)
        return key

    def _label_text(self, key: tuple[str, ...], extra: tuple[tuple[str, str], ...] = ()) -> str:
        pairs = [*zip(self.labels, key, strict=True), *extra]
        return "{" + ",".join(f'{name}="{_escape(value)}"' for name, value in pairs) + "}" if pairs else ""

    def header(self) -> list[str]:
        return [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}"]


class Counter(_Metric):
    kind = "counter"

    def inc(self, amount: float = 1, **labels: Any) -> None:
        if amount <= 0:
            return
        key = self._key(labels)
        self.series[key] = self.series.get(key, 0) + amount

    def render(self, rename: Callable[[tuple[str, ...]], tuple[str, ...]] = lambda key: key) -> list[str]:
        merged: dict[tuple[str, ...], float] = {}
        for key, value in self.series.items():
            merged[rename(key)] = merged.get(rename(key), 0) + value
        return self.header() + [f"{self.name}{self._label_text(key)} {_number(value)}"
                                for key, value in sorted(merged.items())]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...], buckets: tuple[float, ...]) -> None:
        super().__init__(name, help_text, labels)
        self.buckets = (*buckets, math.inf)

    def observe(self, value: float, **labels: Any) -> None:
        if value is None or value < 0:
            return
        key = self._key(labels)
        counts, total = self.series.get(key) or ([0] * len(self.buckets), 0.0)
        for index, bound in enumerate(self.buckets):
            if value <= bound:
                counts[index] += 1
        self.series[key] = (counts, total + value)

    def render(self, rename: Callable[[tuple[str, ...]], tuple[str, ...]] = lambda key: key) -> list[str]:
        merged: dict[tuple[str, ...], tuple[list[int], float]] = {}
        for key, (counts, total) in self.series.items():
            seen_counts, seen_total = merged.get(rename(key)) or ([0] * len(self.buckets), 0.0)
            merged[rename(key)] = ([a + b for a, b in zip(seen_counts, counts, strict=True)], seen_total + total)
        lines = self.header()
        for key, (counts, total) in sorted(merged.items()):
            for bound, count in zip(self.buckets, counts, strict=True):
                lines.append(f"{self.name}_bucket{self._label_text(key, (('le', _number(bound)),))} {count}")
            lines.append(f"{self.name}_sum{self._label_text(key)} {_number(total)}")
            lines.append(f"{self.name}_count{self._label_text(key)} {counts[-1]}")
        return lines


class Gauge(_Metric):
    kind = "gauge"

    def set(self, value: float, **labels: Any) -> None:
        self.series[self._key(labels)] = float(value)

    def render(self, rename: Callable[[tuple[str, ...]], tuple[str, ...]] = lambda key: key) -> list[str]:
        return self.header() + [f"{self.name}{self._label_text(rename(key))} {_number(value)}"
                                for key, value in sorted(self.series.items())]
