"""Process and runtime metrics of the api and the worker: request latency, the database pool, the event loop, the
process itself and the build (``octryx_api_request_duration_seconds``, ``octryx_db_pool_*``,
``octryx_event_loop_lag_seconds``, ``process_*``, ``octryx_build_info``).

All in memory or read from the running process at scrape time; nothing queries the database.

- Request latency per endpoint (route template) and method: observed by the request middleware.
- The pool: SQLAlchemy's ``QueuePool`` status (size, checked out, idle, overflow) and the requests that gave up
  waiting for a connection (``sqlalchemy.exc.TimeoutError`` reaching the middleware; an exhausted
  pool can take the API out of service).
- Event loop lag: a light task (started with the first scrape) sleeps ``LAG_TICK_SECONDS`` and measures how late it
  wakes; the gauge is the worst lag of the last ``LAG_WINDOW_SECONDS``.
- ``process_*`` in the names Prometheus' client libraries use (Linux ``/proc``; elsewhere what ``resource`` offers).
"""

from __future__ import annotations

import asyncio
import os
import resource
import sys
import time
from collections import deque
from typing import Any

from .metric_types import Counter, Histogram, _escape, _number

API_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
LAG_TICK_SECONDS = 0.5
LAG_WINDOW_SECONDS = 60.0

API_DURATION = Histogram("octryx_api_request_duration_seconds", "API request duration in seconds by endpoint (route"
                         " template) and method", ("endpoint", "method"), API_SECONDS)
POOL_TIMEOUTS = Counter("octryx_db_pool_timeouts_total", "Requests that gave up waiting for a database connection",
                        ())

_STARTED = time.time()
_lags: deque[tuple[float, float]] = deque(maxlen=int(LAG_WINDOW_SECONDS / LAG_TICK_SECONDS) + 10)
_monitor: asyncio.Task[None] | None = None


def reset() -> None:
    """Tests: start empty."""
    API_DURATION.series.clear()
    POOL_TIMEOUTS.series.clear()
    _lags.clear()


def record_api_duration(endpoint: str, method: str, seconds: float) -> None:
    API_DURATION.observe(seconds, endpoint=endpoint, method=method)


def record_pool_timeout() -> None:
    POOL_TIMEOUTS.inc()


# ---- event loop -----------------------------------------------------------------------------------------------------

async def _measure_lag() -> None:
    while True:
        started = time.monotonic()
        await asyncio.sleep(LAG_TICK_SECONDS)
        now = time.monotonic()
        _lags.append((now, max(0.0, now - started - LAG_TICK_SECONDS)))


def ensure_loop_monitor() -> None:
    """Start the lag task in this process's running loop once (a new loop, as in tests, gets its own)."""
    global _monitor
    loop = asyncio.get_running_loop()
    if _monitor is not None and not _monitor.done() and _monitor.get_loop() is loop:
        return
    _monitor = loop.create_task(_measure_lag(), name="octryx-event-loop-lag")


def event_loop_lag() -> float | None:
    cutoff = time.monotonic() - LAG_WINDOW_SECONDS
    recent = [lag for at, lag in _lags if at >= cutoff]
    return max(recent) if recent else None


# ---- process --------------------------------------------------------------------------------------------------------

def _process() -> dict[str, float]:
    times = os.times()
    values = {"process_cpu_seconds_total": times.user + times.system, "process_start_time_seconds": _STARTED}
    try:
        with open("/proc/self/statm") as statm:
            values["process_resident_memory_bytes"] = int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        values["process_open_fds"] = len(os.listdir("/proc/self/fd"))
    except OSError:  # not Linux: the peak resident set (bytes on macOS, KiB elsewhere)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        values["process_resident_memory_bytes"] = peak if sys.platform == "darwin" else peak * 1024
    return values


_PROCESS_HELP = {
    "process_cpu_seconds_total": ("counter", "User and system CPU time spent in seconds"),
    "process_start_time_seconds": ("gauge", "Start time of the process since the Unix epoch in seconds"),
    "process_resident_memory_bytes": ("gauge", "Resident memory size in bytes"),
    "process_open_fds": ("gauge", "Number of open file descriptors"),
}


# ---- rendering ------------------------------------------------------------------------------------------------------

def _pool_status(engine: Any) -> dict[str, float] | None:
    pool = getattr(getattr(engine, "sync_engine", engine), "pool", None)
    if pool is None or not all(hasattr(pool, name) for name in ("size", "checkedout", "checkedin", "overflow")):
        return None  # SQLite's pools have no fixed size
    return {"size": pool.size(), "checked_out": pool.checkedout(), "idle": pool.checkedin(),
            "overflow": max(0, pool.overflow()), "max_overflow": getattr(pool, "_max_overflow", 0)}


def render(engine: Any, *, app_version: str) -> list[str]:
    lines = [*API_DURATION.render(), *POOL_TIMEOUTS.render()]
    pool = _pool_status(engine)
    if pool is not None:
        lines += ["# HELP octryx_db_pool_size Configured size of the database connection pool",
                  "# TYPE octryx_db_pool_size gauge", f"octryx_db_pool_size {pool['size']}",
                  "# HELP octryx_db_pool_max_overflow Connections the pool may open above its size",
                  "# TYPE octryx_db_pool_max_overflow gauge", f"octryx_db_pool_max_overflow {pool['max_overflow']}",
                  "# HELP octryx_db_pool_connections Database pool connections by state (checked_out, idle,"
                  " overflow)", "# TYPE octryx_db_pool_connections gauge"]
        lines += [f'octryx_db_pool_connections{{state="{state}"}} {pool[state]}'
                  for state in ("checked_out", "idle", "overflow")]
    lag = event_loop_lag()
    if lag is not None:
        lines += ["# HELP octryx_event_loop_lag_seconds Worst event loop lag of the last minute in seconds",
                  "# TYPE octryx_event_loop_lag_seconds gauge", f"octryx_event_loop_lag_seconds {_number(lag)}"]
    for name, value in _process().items():
        kind, help_text = _PROCESS_HELP[name]
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", f"{name} {_number(value)}"]
    lines += ["# HELP octryx_build_info The running Octryx version (always 1)", "# TYPE octryx_build_info gauge",
              f'octryx_build_info{{version="{_escape(app_version)}"}} 1']
    return lines
