"""The user's own seat allowance and daily budget for the status block (root judge finding 4).

Read with the launcher's own gateway login from ``GET /api/v1/agent-gateway/daily-budget?workspace_id=``:
``{state, reason, limit_usd, spent_usd, resets_at, seat_allowance}``. The seat allowance is the latest 5h/7d
utilization Anthropic reported on one of the user's seat sessions; the budget is the Workspace's per-user daily
limit against the user's gateway spend of the UTC day. Labels carry numbers and fixed codes only; a value that is
not a finite, plausible number is not shown. Times are local ``HH:MM``.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from .platform import PlatformResult, SessionContext, call_control_plane, safe_code
from .state import LocalState

TIMEOUT = 5.0
PATH = "/daily-budget"
_MAX_USD = 1_000_000.0
_MAX_PCT = 10_000.0


def fetch_usage(state: LocalState, context: SessionContext, *, http: httpx.Client) -> PlatformResult:
    return call_control_plane(state, context, "GET", f"{PATH}?workspace_id={quote(context.workspace_id, safe='')}",
                              http=http, timeout=TIMEOUT)


def _number(value: Any, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0.0 <= number <= maximum else None


def _epoch(value: Any) -> float | None:
    """An ISO UTC timestamp (``...Z``) as epoch seconds, or ``None``."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.timestamp() if parsed.tzinfo is not None else None


def _clock(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def _codes(result: PlatformResult) -> str:
    return "/".join(part for part in (result.state, result.reason) if part) or (
        str(result.status_code) if result.status_code else result.outcome)


def budget_label(result: PlatformResult) -> str:
    if result.outcome != "ok":
        return f"unavailable ({_codes(result)})"
    if result.state == "needs_configuration":
        return f"not configured ({result.reason or 'needs_configuration'})"
    limit = _number(result.body.get("limit_usd"), _MAX_USD)
    spent = _number(result.body.get("spent_usd"), _MAX_USD)
    if result.state not in ("allowed", "denied") or limit is None or spent is None:
        return "unavailable (invalid_response)"
    resets = _epoch(result.body.get("resets_at"))
    label = f"{spent:.2f} / {limit:.2f} USD today"
    if result.state == "denied":
        label += f", used up ({safe_code(result.reason) or 'denied'})"
    return label + (f" (resets {_clock(resets)})" if resets is not None else "")


def _window(name: str, pct: Any, resets_at: Any, now: float) -> str:
    value = _number(pct, _MAX_PCT)
    resets = _epoch(resets_at)
    if value is None:
        return f"{name} n/a"
    if resets is not None and resets <= now:
        return f"{name} reset since"
    return f"{name} {value:.0f}%"


def allowance_label(result: PlatformResult, *, now: float | None = None) -> str:
    if result.outcome != "ok":
        return f"unavailable ({_codes(result)})"
    allowance = result.body.get("seat_allowance")
    if not isinstance(allowance, dict):
        return "not reported yet (shown after a seat turn)"
    current = time.time() if now is None else now
    parts = [_window("5h", allowance.get("five_hour_pct"), allowance.get("five_hour_resets_at"), current),
             _window("7d", allowance.get("seven_day_pct"), allowance.get("seven_day_resets_at"), current)]
    label = " · ".join(parts)
    if safe_code(allowance.get("status")) == "rejected":
        label += ", limit reached"
    updated = _epoch(allowance.get("updated_at"))
    return label + (f" (as of {_clock(updated)})" if updated is not None else "")


__all__ = ["allowance_label", "budget_label", "fetch_usage"]
