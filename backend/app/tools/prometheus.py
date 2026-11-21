"""Prometheus tool implementation.

The range query runs over an explicit window: ``start``/``end`` (RFC3339), else the alert scope's window, else
the relative ``duration`` (default ``1h``); the span is at most 24 h. Under an alert scope the window is
clamped to the alert's and every selector must name the target's labels. Any transport error, non-200 answer or a
``status`` other than ``success`` is ``unavailable`` with an ``error`` — never an empty result; an empty vector is
``empty``.
"""

from datetime import timedelta
from math import ceil
from typing import Any

import httpx

from ..services.workflow_checks.evidence_families import (
    EMPTY,
    OK,
    REFUSED,
    UNAVAILABLE,
    evidence_envelope,
    with_envelope,
)
from ..time_utils import utc_now_aware
from .alert_scope import AlertScope, promql_scope_refusal, query_window, rfc3339, run_alert_scope
from .context import ToolContext

MAX_POINTS = 1000


class PrometheusUnavailableError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _envelope(status: str, scope: AlertScope | None, window: dict | None, count: int, reason: str = "") -> dict:
    return evidence_envelope("metrics", status, target_id=scope.target_id if scope else None,
                             namespace=scope.namespace if scope else None, window=window, count=count, reason=reason)


async def _get_data(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    """The ``data`` of a successful Prometheus API answer; anything else raises :class:`PrometheusUnavailableError`."""
    try:
        resp = await client.get(url, params=params)
    except httpx.HTTPError as error:
        raise PrometheusUnavailableError(f"prometheus_unreachable: {type(error).__name__}") from error
    if resp.status_code != 200:
        raise PrometheusUnavailableError(f"prometheus_http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as error:
        raise PrometheusUnavailableError("prometheus_invalid_response") from error
    if not isinstance(body, dict) or body.get("status") != "success" or not isinstance(body.get("data"), dict):
        error_type = str(body.get("errorType") or "error") if isinstance(body, dict) else "error"
        raise PrometheusUnavailableError(f"prometheus_status_{error_type}"[:80])
    return body["data"]


def _series(data: dict[str, Any]) -> int:
    result = data.get("result")
    if isinstance(result, list):
        return len(result)
    return 1 if result not in (None, "", []) and data.get("resultType") in ("scalar", "string") else 0


class QueryPrometheus:
    name = "query_prometheus"
    description = "Execute a PromQL query against Prometheus"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await run_alert_scope(context)
        prometheus_url = context.project_config.get("prometheus_url")
        if not prometheus_url:
            return with_envelope({"error": "No Prometheus URL configured for this project"},
                                 _envelope(UNAVAILABLE, scope, None, 0, "prometheus_not_configured"))

        query = str(params.get("query") or "")
        duration = str(params.get("duration") or "1h")
        refusal = promql_scope_refusal(query, scope.metrics_selector) if scope else None
        bounds = query_window(params, scope, now=utc_now_aware(), default_span=self._parse_duration(duration))
        if refusal is None and isinstance(bounds, str):
            refusal = bounds
        if refusal is not None:
            return with_envelope({"error": refusal, "code": refusal, "query": query},
                                 _envelope(REFUSED, scope, scope.window() if scope else None, 0, refusal))
        start, end = bounds
        window = {"start": rfc3339(start), "end": rfc3339(end)}
        step = max(60, ceil((end - start).total_seconds() / MAX_POINTS))

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                instant = await _get_data(client, f"{prometheus_url}/api/v1/query",
                                          {"query": query, "time": window["end"]})
                range_data = await _get_data(client, f"{prometheus_url}/api/v1/query_range",
                                             {"query": query, "start": window["start"], "end": window["end"],
                                              "step": str(step)})
        except PrometheusUnavailableError as error:
            return with_envelope({"error": error.code, "code": error.code, "query": query},
                                 _envelope(UNAVAILABLE, scope, window, 0, error.code))

        count = max(_series(instant), _series(range_data))
        return with_envelope({
            "query": query,
            "duration": duration,
            "start": window["start"],
            "end": window["end"],
            "step": step,
            "instant_result": instant,
            "range_result": range_data,
        }, _envelope(OK if count else EMPTY, scope, window, count))

    def _parse_duration(self, duration: str) -> timedelta:
        try:
            unit = duration[-1]
            value = int(duration[:-1])
        except (IndexError, ValueError):
            return timedelta(hours=1)
        if unit == "h":
            return timedelta(hours=value)
        elif unit == "m":
            return timedelta(minutes=value)
        elif unit == "d":
            return timedelta(days=value)
        return timedelta(hours=1)
