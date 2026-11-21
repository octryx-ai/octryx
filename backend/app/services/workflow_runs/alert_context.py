"""The alert on a workflow run: one versioned shape, and the readers every consumer uses.

An Action started by an inbound alert binds its session to a workflow run (``automation.start_action_run``); the
run's ``context`` then carries:

* ``alert``: what the alert says, bounded and data only (title, status, severity, source, reference, summary,
  fingerprint, the ``(alert fingerprint, startsAt)`` occurrence pairs, the common labels), plus what the server
  decided about it: the time ``window`` evidence is read in, the mapped ``target_id`` and the ``dedup`` decision;
* ``alert_target``: the mapped target's server-side context (``inbound_alerts.targets.AlertTarget.as_context``), or
  nothing when the alert maps to no target.

The window is ``startsAt − lookback`` (the target's ``lookback_minutes``, default 30, at most 24 h) up to the end of
a resolved alert, or open ("up to the query time") while it fires. An alert without a start (an older run input, a
source that sends none) starts its window ``lookback`` before the run started.

Nothing here is ever taken from the model: the readers read the run the session is bound to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..inbound_alerts.normalize import MAX_OCCURRENCES, iso_instant, parse_instant

ALERT_CONTEXT_VERSION = 1
DEFAULT_LOOKBACK_MINUTES = 30
MAX_LOOKBACK_MINUTES = 24 * 60
MAX_SUMMARY = 500
_TEXT_FIELDS = ("title", "status", "severity", "source_type", "reference")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _lookback(value: Any) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LOOKBACK_MINUTES
    return max(0, min(minutes, MAX_LOOKBACK_MINUTES))


def alert_window(alert: dict, *, lookback_minutes: int, now: datetime) -> dict:
    """``{"start", "end"}`` as ISO UTC instants; ``end`` is ``None`` while the alert fires (up to the query time)."""
    current = _aware(now)
    started = parse_instant((alert or {}).get("starts_at"))
    anchor = min(started, current) if started else current  # a start in the future never opens a future window
    start = anchor - timedelta(minutes=_lookback(lookback_minutes))
    end: datetime | None = None
    if str((alert or {}).get("status") or "") == "resolved":
        ended = parse_instant((alert or {}).get("ends_at"))
        end = max(min(ended, current), start) if ended else current
    return {"start": iso_instant(start), "end": iso_instant(end) if end else None}


def _occurrences(raw: Any) -> list[list[str]]:
    pairs = []
    for item in raw if isinstance(raw, list | tuple) else []:
        if isinstance(item, list | tuple) and len(item) == 2:
            pairs.append([str(item[0])[:64], str(item[1])[:40]])
    return pairs[:MAX_OCCURRENCES]


def alert_run_context(inbound_alert: dict, *, now: datetime) -> dict:
    """The run context of an alert-started run: ``{"alert": {...}, "alert_target": {...} | None}``."""
    inbound = inbound_alert if isinstance(inbound_alert, dict) else {}
    alert = inbound.get("alert") if isinstance(inbound.get("alert"), dict) else {}
    target = inbound.get("target") if isinstance(inbound.get("target"), dict) else None
    dedup = inbound.get("dedup") if isinstance(inbound.get("dedup"), dict) else None
    lookback = (target or {}).get("lookback_minutes", DEFAULT_LOOKBACK_MINUTES)
    labels = alert.get("common_labels") if isinstance(alert.get("common_labels"), dict) else {}
    context = {
        "v": ALERT_CONTEXT_VERSION,
        **{name: str(alert.get(name) or "")[:300] for name in _TEXT_FIELDS},
        "summary": str(alert.get("summary") or "")[:MAX_SUMMARY],
        "fingerprint": str(alert.get("fingerprint") or "")[:64],
        "occurrences": _occurrences(alert.get("occurrences")),
        "common_labels": {str(key): str(value) for key, value in labels.items()},
        "window": alert_window(alert, lookback_minutes=lookback, now=now),
        "target_id": str(target.get("id") or "") or None if target else None,
        "dedup": dict(dedup) if dedup else None,
        "test": bool(inbound.get("is_test")),
        "event_id": inbound.get("event_id"),
        "webhook_id": inbound.get("webhook_id"),
    }
    return {"alert": context, "alert_target": dict(target) if target else None}


def _context(run: Any) -> dict[str, Any]:
    context = getattr(run, "context", None)
    return context if isinstance(context, dict) else {}


def alert_of(run: Any) -> dict | None:
    alert = _context(run).get("alert")
    return alert if isinstance(alert, dict) else None


def alert_target_of(run: Any) -> dict | None:
    target = _context(run).get("alert_target")
    return target if isinstance(target, dict) else None


def alert_window_of(run: Any) -> tuple[datetime, datetime | None] | None:
    """The run's alert window as aware UTC datetimes; ``None`` without an alert or a readable window."""
    window = (alert_of(run) or {}).get("window")
    if not isinstance(window, dict):
        return None
    start = parse_instant(window.get("start"))
    if start is None:
        return None
    return start, parse_instant(window.get("end"))


__all__ = [
    "ALERT_CONTEXT_VERSION",
    "DEFAULT_LOOKBACK_MINUTES",
    "MAX_LOOKBACK_MINUTES",
    "alert_of",
    "alert_run_context",
    "alert_target_of",
    "alert_window",
    "alert_window_of",
]
