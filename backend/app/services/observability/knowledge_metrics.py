"""Knowledge first, measured: how often the Workspace knowledge answered before the web was asked."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .metric_types import Counter, _Metric

PLATFORM_TOOL_PREFIX = "mcp__octryx-knowledge__"
KNOWLEDGE_TOOL = "knowledge_search"
WEB_TOOLS = ("web_search", "web_fetch")
COUNTED_TOOLS = (KNOWLEDGE_TOOL, *WEB_TOOLS)
HIT, MISS, ERROR, UNKNOWN = "hit", "miss", "error", "unknown"
# The engines' own web tools (names as ``read_evidence.NATIVE_WEB_EVIDENCE``, ``tool_policy.CODEX_SEARCH_TOOLS``,
# ``seat_transcript.HOSTED_SEARCH_TOOL``; repeated here: stdlib imports only).
NATIVE_WEB_TOOLS = {
    "WebSearch": "web_search_native", "WebFetch": "web_fetch_native",
    **dict.fromkeys(("webrun", "web.run", "web__run", "mcp__codex_apps__search_service__web_run",
                     "codex_hosted_web_search"), "web_search_native"),
}
ATTRIBUTED_SERIES = 2000  # as ``agent_metrics.ATTRIBUTED_SERIES`` (LLM tokens)

_STATE = re.compile(r'"state"\s*:\s*"([a-z_]+)"')
_COUNT = re.compile(r'"count"\s*:\s*(\d+)')
_RESULT_COUNT = re.compile(r'"result_count"\s*:\s*(\d+)')
_CLIENT_ERROR = re.compile(r"Client error '4\d\d|\b4\d\d (Client Error|Not Found|Forbidden|Unauthorized|Gone)\b")

KNOWLEDGE_QUERIES = Counter(
    "octryx_knowledge_queries_total",
    "Knowledge and web lookups by tool (knowledge_search, web_search, web_fetch, web_search_native,"
    " web_fetch_native) and outcome:"
    " hit (a search answered ok with results; a fetch returned content), miss (a search answered ok without results;"
    " a fetch returned no content, was denied by the source rules or answered 4xx), error (tool error, unavailable,"
    " transport, connection failure, 5xx), unknown (only web_search_native / web_fetch_native, the engines' own web"
    " tools, whose result is not judged); by phase, workflow (none outside a run), engine and Workspace",
    ("tool", "outcome", "phase", "workflow", "engine", "workspace"), max_series=ATTRIBUTED_SERIES)

METRICS: tuple[_Metric, ...] = (KNOWLEDGE_QUERIES,)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()


def _text(result: dict[str, Any]) -> str:
    return str(result.get("excerpt") or result.get("output") or "")


def knowledge_hits(result: dict[str, Any]) -> bool:
    text = _text(result)
    state, count = _STATE.search(text), _RESULT_COUNT.search(text)
    return bool(state and state.group(1) == "ok" and count and int(count.group(1)) > 0)


def web_result_ok(tool: str, result: dict[str, Any]) -> bool:
    if tool not in WEB_TOOLS:
        return True
    text = _text(result)
    if tool == "web_search":
        state = _STATE.search(text)
        count = _COUNT.search(text)
        return bool(state and state.group(1) == "ok" and (count is None or int(count.group(1)) > 0))
    head = text.lstrip()[:200]
    return bool(text.strip()) and '"error"' not in head and '"state": "denied"' not in head


def query_outcome(tool: str, status: str | None, result: Any) -> str:
    result = result if isinstance(result, dict) else {}
    if (status or "success") != "success" or result.get("is_error") is True:
        return ERROR
    text = _text(result)
    if tool == "web_fetch":
        head = text.lstrip()[:300]
        if web_result_ok(tool, result):
            return HIT
        if not text.strip() or '"state": "denied"' in head or _CLIENT_ERROR.search(head):
            return MISS
        return ERROR
    state = _STATE.search(text)
    if not state or state.group(1) != "ok":
        return ERROR
    found = knowledge_hits(result) if tool == KNOWLEDGE_TOOL else web_result_ok(tool, result)
    return HIT if found else MISS


def lookup(row: Any) -> tuple[str, str] | None:
    name = str(row.tool_name or "")
    if name in NATIVE_WEB_TOOLS:
        return NATIVE_WEB_TOOLS[name], UNKNOWN
    tool = name.removeprefix(PLATFORM_TOOL_PREFIX)
    if tool == name or tool not in COUNTED_TOOLS:
        return None
    return tool, query_outcome(tool, row.status, row.result)


def tool_call(row: Any, context: dict[str, str], engine: str) -> Callable[[], None] | None:
    found = lookup(row)
    if found is None:
        return None
    labels = {"tool": found[0], "outcome": found[1],
              "phase": context.get("phase") or "none", "workflow": context.get("workflow") or "none",
              "engine": engine, "workspace": context.get("workspace") or "none"}
    return lambda: KNOWLEDGE_QUERIES.inc(**labels)


def phase_usage(rows: Any, since: Any = None) -> dict[str, int]:
    usage = {"knowledge_hits": 0, "knowledge_misses": 0, "knowledge_errors": 0, "web_calls": 0, "web_hits": 0}
    for row in rows:
        created = getattr(row, "created_at", None)
        if since is not None and (created is None or created < since):
            continue
        found = lookup(row)
        if found is None:
            continue
        tool, outcome = found
        if tool == KNOWLEDGE_TOOL:
            usage[{HIT: "knowledge_hits", MISS: "knowledge_misses"}.get(outcome, "knowledge_errors")] += 1
        else:
            usage["web_calls"] += 1
            usage["web_hits"] += outcome == HIT
    return usage


__all__ = ["COUNTED_TOOLS", "ERROR", "HIT", "KNOWLEDGE_QUERIES", "METRICS", "MISS", "NATIVE_WEB_TOOLS", "UNKNOWN",
           "knowledge_hits", "lookup", "phase_usage", "query_outcome", "reset", "tool_call", "web_result_ok"]
