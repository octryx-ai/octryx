"""The seat allowance as Prometheus gauges.

Metrics never go through the database, not even at scrape time. The seat routes
set the gauges in memory where the account's answer arrives (``presence.record_allowance``: Claude Code's 5h/7d
utilization, Codex's primary/secondary windows) and ``/metrics`` prints that memory. They run in the API process, so
only the API's ``/metrics`` reports them; after a restart the series are absent until the next seat answer. No person
label: the newest allowance per engine. A value that is missing is not exported (no 0, no NaN).

- ``octryx_seat_allowance_used_ratio{engine, window}``: 0..1 of the window used (``window``: ``5h`` | ``7d``);
- ``octryx_seat_allowance_resets_timestamp_seconds{engine, window}``: when the window resets (Unix seconds);
- ``octryx_seat_allowance_updated_timestamp_seconds{engine}``: when the allowance was last reported.
"""

from __future__ import annotations

import math
import threading
from datetime import UTC, datetime
from typing import Any

USED = "octryx_seat_allowance_used_ratio"
RESETS = "octryx_seat_allowance_resets_timestamp_seconds"
UPDATED = "octryx_seat_allowance_updated_timestamp_seconds"
_HELP = {
    USED: "Share of the seat's usage window used (0..1), newest report per engine.",
    RESETS: "When the seat's usage window resets, Unix seconds.",
    UPDATED: "When the seat's allowance was last reported, Unix seconds.",
}
_ENGINES = ("claude_code", "codex")
_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def _seconds(value: datetime | None) -> float | None:
    if value is None:
        return None
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).timestamp()


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def observe(engine: str, allowance: Any, *, at: datetime) -> None:
    """The newest allowance of ``engine``'s seat (its stored values after this answer)."""
    if engine not in _ENGINES:
        return
    windows: dict[str, dict[str, float]] = {}
    for window, pct, resets in (("5h", allowance.five_hour_pct, allowance.five_hour_resets_at),
                                ("7d", allowance.seven_day_pct, allowance.seven_day_resets_at)):
        values: dict[str, float] = {}
        if isinstance(pct, (int, float)) and math.isfinite(pct):
            values["ratio"] = round(float(pct) / 100.0, 4)
        if (seconds := _seconds(resets)) is not None:
            values["resets"] = float(int(seconds))
        windows[window] = values
    with _lock:
        _state[engine] = {"windows": windows, "updated": float(int(_seconds(at) or 0))}


def reset() -> None:
    with _lock:
        _state.clear()


def seat_allowance_lines() -> list[str]:
    """The gauges as Prometheus text lines, from memory only."""
    with _lock:
        state = {engine: dict(value) for engine, value in _state.items()}
    series: dict[str, list[str]] = {USED: [], RESETS: [], UPDATED: []}
    for engine in sorted(state):
        for window, values in state[engine]["windows"].items():
            labels = f'{{engine="{engine}",window="{window}"}}'
            if "ratio" in values:
                series[USED].append(f"{USED}{labels} {_number(values['ratio'])}")
            if "resets" in values:
                series[RESETS].append(f"{RESETS}{labels} {_number(values['resets'])}")
        if state[engine]["updated"]:
            series[UPDATED].append(f'{UPDATED}{{engine="{engine}"}} {_number(state[engine]["updated"])}')
    lines: list[str] = []
    for name, values in series.items():
        if values:
            lines += [f"# HELP {name} {_HELP[name]}", f"# TYPE {name} gauge", *values]
    return lines


__all__ = ["RESETS", "UPDATED", "USED", "observe", "reset", "seat_allowance_lines"]
