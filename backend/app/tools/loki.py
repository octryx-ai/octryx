"""Loki tool implementation.

Every query has an explicit window (``start``/``end`` sent to Loki): the alert scope's window by default, else
the last hour; ``since`` (``30m``) or ``start``/``end`` (RFC3339) narrow it, the span is at most 24 h and ``limit``
at most 1000. Under an alert scope the window is clamped to the alert's and every stream selector must name the
target's labels. A transport or HTTP error is ``unavailable``, never an empty answer.
"""

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
from .alert_scope import AlertScope, logql_scope_refusal, query_window, rfc3339, run_alert_scope
from .context import ToolContext

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100


def _limit(value: Any) -> int:
    try:
        limit = int(value) if value is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _envelope(status: str, scope: AlertScope | None, window: dict | None, count: int, reason: str = "") -> dict:
    return evidence_envelope("logs", status, target_id=scope.target_id if scope else None,
                             namespace=scope.namespace if scope else None, window=window, count=count, reason=reason)


class QueryLoki:
    name = "query_loki"
    description = "Search logs via Loki with LogQL"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await run_alert_scope(context)
        loki_url = context.project_config.get("loki_url")
        if not loki_url:
            return with_envelope({"error": "No Loki URL configured for this project"},
                                 _envelope(UNAVAILABLE, scope, None, 0, "loki_not_configured"))

        query = str(params.get("query") or "")
        limit = _limit(params.get("limit"))
        refusal = logql_scope_refusal(query, scope.logs_selector) if scope else None
        bounds = query_window(params, scope, now=utc_now_aware())
        if refusal is None and isinstance(bounds, str):
            refusal = bounds
        if refusal is not None:
            return with_envelope({"error": refusal, "code": refusal, "query": query},
                                 _envelope(REFUSED, scope, scope.window() if scope else None, 0, refusal))
        start, end = bounds
        window = {"start": rfc3339(start), "end": rfc3339(end)}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(
                    f"{loki_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "limit": limit,
                        "direction": "backward",
                        "start": window["start"],
                        "end": window["end"],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as error:
            code = f"loki_http_{error.response.status_code}"
            return with_envelope({"error": code, "code": code, "query": query},
                                 _envelope(UNAVAILABLE, scope, window, 0, code))
        except (httpx.HTTPError, ValueError) as error:
            code = f"loki_unreachable: {type(error).__name__}"
            return with_envelope({"error": code, "code": "loki_unreachable", "query": query},
                                 _envelope(UNAVAILABLE, scope, window, 0, code))

        streams = data.get("data", {}).get("result", []) if isinstance(data, dict) else []
        streams = streams if isinstance(streams, list) else []
        total_lines = sum(len(s.get("values", [])) for s in streams if isinstance(s, dict))

        return with_envelope({
            "query": query,
            "start": window["start"],
            "end": window["end"],
            "limit": limit,
            "total_lines": total_lines,
            "streams_count": len(streams),
            "streams": streams,
        }, _envelope(OK if total_lines else EMPTY, scope, window, total_lines))
