"""HTTP request metrics: Prometheus counters and a bounded in-memory window.

Requests are counted in memory only, never in the database: the Prometheus counter on ``/metrics`` and a one-hour window
of (time, status, duration) samples that Observability → Health reads for the API row (request rate, 5xx, p95). Per
process; a restart starts empty.
"""

from __future__ import annotations

import re
import time
from collections import Counter, deque
from typing import Any

from . import runtime_metrics

_HTTP_REQUEST_COUNTER: Counter[tuple[str, str, str]] = Counter()
_PREFETCH_FAILURE_COUNTER: Counter[str] = Counter()
WINDOW_SECONDS = 3600
_MAX_SAMPLES = 50_000
_RECENT: deque[tuple[float, int, int]] = deque(maxlen=_MAX_SAMPLES)
_UUID_PATH_SEGMENT_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


def _normalize_endpoint(endpoint: str) -> str:
    """Normalize endpoint path for consistent metrics bucketing."""
    if not endpoint:
        return "unknown"
    normalized = endpoint.strip().rstrip("/") or "/"
    return _UUID_PATH_SEGMENT_RE.sub("/{id}", normalized)


def record_request_counter(endpoint: str, method: str, status_code: int, duration_ms: int = 0) -> None:
    normalized = _normalize_endpoint(endpoint)
    _HTTP_REQUEST_COUNTER[(normalized, method.upper(), str(status_code))] += 1
    runtime_metrics.record_api_duration(normalized, method.upper(), max(0, int(duration_ms)) / 1000)
    _RECENT.append((time.monotonic(), int(status_code), max(0, int(duration_ms))))


def recent_request_summary(window_seconds: int = WINDOW_SECONDS) -> dict[str, Any]:
    """Requests, 5xx and p95 duration of this process in the last ``window_seconds``."""
    cutoff = time.monotonic() - window_seconds
    while _RECENT and _RECENT[0][0] < cutoff:
        _RECENT.popleft()
    durations = sorted(sample[2] for sample in _RECENT)
    return {
        "window_seconds": window_seconds,
        "requests": len(_RECENT),
        "errors_5xx": sum(1 for sample in _RECENT if sample[1] >= 500),
        "p95_ms": durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None,
    }


def reset_recent_requests() -> None:
    _RECENT.clear()
