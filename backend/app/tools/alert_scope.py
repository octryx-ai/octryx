"""The alert scope of a tool call: the mapped target and window of the run the session is bound to.

An alert-started run of incident analysis carries its mapped target (``context.alert_target``) and the alert
window (``context.alert.window``). The evidence tools read both here, from the server's run record and never
from the model's parameters, and bind their query to them: Kubernetes to the target's namespace (and connection),
Loki and Prometheus to its selectors and the window, Jenkins to its jobs. ``None``: the call is not under an alert
scope (chat, or a run without a mapped target) and the tools behave.

The helpers here are pure: the time window arithmetic (RFC3339, ``since``, the 24 h span cap, the clamp to the
scope) and the selector containment check for LogQL and PromQL.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .context import ToolContext

MAX_SPAN = timedelta(hours=24)
DEFAULT_SPAN = timedelta(hours=1)
WINDOW_OUT_OF_SCOPE = "window_out_of_scope"
QUERY_OUT_OF_SCOPE = "query_out_of_scope"
INVALID_WINDOW = "invalid_window"


@dataclass(frozen=True)
class AlertScope:
    target_id: str
    namespace: str | None = None
    connection_id: str | None = None
    logs_selector: str | None = None
    metrics_selector: str | None = None
    jenkins_jobs: tuple[str, ...] = ()
    window_start: datetime | None = None
    window_end: datetime | None = None

    def window(self) -> dict[str, str | None] | None:
        if self.window_start is None:
            return None
        return {"start": rfc3339(self.window_start), "end": rfc3339(self.window_end) if self.window_end else None}


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _section(target: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = target.get(key)
    return value if isinstance(value, Mapping) else {}


def scope_from(target: Mapping[str, Any] | None, window: tuple[datetime, datetime | None] | None) -> AlertScope | None:
    """The scope of an alert target context (``AlertTarget.as_context``) and the alert window."""
    if not isinstance(target, Mapping):
        return None
    target_id = _text(target.get("id") or target.get("target_id"))
    if target_id is None:
        return None
    kubernetes, ci = _section(target, "kubernetes"), _section(target, "ci")
    jobs = ci.get("jenkins_jobs") if isinstance(ci.get("jenkins_jobs"), list | tuple) else []
    start, end = (window if window else (None, None))
    return AlertScope(
        target_id=target_id,
        namespace=_text(kubernetes.get("namespace")),
        connection_id=_text(kubernetes.get("connection_id")),
        logs_selector=_text(_section(target, "logs").get("selector")),
        metrics_selector=_text(_section(target, "metrics").get("selector")),
        jenkins_jobs=tuple(job for job in (_text(item) for item in jobs) if job),
        window_start=as_utc(start) if start else None,
        window_end=as_utc(end) if end else None,
    )


async def run_alert_scope(context: ToolContext) -> AlertScope | None:
    """The alert scope of the run ``context``'s session is bound to; ``None`` without one."""
    if context.db is None or not context.session_id:
        return None
    from ..services.workflow_checks.evidence_families import _alert_readers
    from ..services.workflow_runs.records import active_run_for_session

    run = await active_run_for_session(context.db, context.session_id)
    if run is None:
        return None
    target_of, window_of = _alert_readers()
    return scope_from(target_of(run), window_of(run))


# --- time ---------------------------------------------------------------------------------------------------------


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def rfc3339(value: datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rfc3339(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return as_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


_DURATION = re.compile(r"^(\d{1,5})([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_duration(value: Any) -> timedelta | None:
    match = _DURATION.match(str(value or "").strip())
    if match is None:
        return None
    return timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def query_window(params: Mapping[str, Any], scope: AlertScope | None, *, now: datetime,
                 default_span: timedelta = DEFAULT_SPAN) -> tuple[datetime, datetime] | str:
    """``(start, end)`` of a query, or the refusal code.

    ``start``/``end`` (RFC3339) and ``since`` (``30m``) come from the model; the default is the scope's window, else
    the last ``default_span``. Under a scope the window is clamped to the scope's (``end`` defaults to the query
    time); a window wholly outside it is refused. The span is at most 24 h: under a scope a longer one keeps its
    start (the alert's onset), otherwise its end.
    """
    now = as_utc(now)
    raw_start, raw_end, since = params.get("start"), params.get("end"), params.get("since")
    start, end = parse_rfc3339(raw_start), parse_rfc3339(raw_end)
    if (raw_start not in (None, "") and start is None) or (raw_end not in (None, "") and end is None):
        return INVALID_WINDOW
    span = parse_duration(since) if since not in (None, "") else None
    if since not in (None, "") and span is None:
        return INVALID_WINDOW
    scope_start = scope.window_start if scope else None
    scope_end = (scope.window_end or now) if scope_start else None
    end = end or (scope_end if scope_start else now)
    if start is None:
        start = end - span if span is not None else (scope_start if scope_start else end - default_span)
    if scope_start is not None and scope_end is not None:
        start, end = max(start, scope_start), min(end, scope_end)
    if start >= end:
        return WINDOW_OUT_OF_SCOPE if scope_start is not None else INVALID_WINDOW
    if end - start > MAX_SPAN:
        # Under an alert the onset matters most: the window keeps its start; otherwise the newest 24 h.
        start, end = (start, start + MAX_SPAN) if scope_start is not None else (end - MAX_SPAN, end)
    return start, end


# --- selectors ----------------------------------------------------------------------------------------------------

_MATCHER = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"')
_BRACES = re.compile(r"\{[^{}]*\}")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`')
_GROUPING = re.compile(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)")
_IDENTIFIER = re.compile(r"(?<![\w.:])([A-Za-z_:][A-Za-z0-9_:]*)")
_PROMQL_WORDS = frozenset({"and", "or", "unless", "bool", "offset", "by", "without", "on", "ignoring",
                           "group_left", "group_right", "inf", "nan", "atan2", "start", "end"})


def selector_matchers(selector: str | None) -> dict[str, str]:
    """The exact ``label="value"`` matchers of a target selector (``{namespace="shop",app="checkout"}``)."""
    return {name: value for name, op, value in _MATCHER.findall(str(selector or "")) if op == "="}


def _block_has(block: str, required: dict[str, str]) -> bool:
    exact = {}
    for name, op, value in _MATCHER.findall(block):
        if op == "=":
            exact.setdefault(name, set()).add(value)
    return all(exact.get(name) == {value} for name, value in required.items())


def logql_scope_refusal(query: str, selector: str | None) -> str | None:
    """LogQL: every stream selector names the target's labels exactly (``None``: in scope)."""
    required = selector_matchers(selector)
    if not required:
        return None
    blocks = _BRACES.findall(_strip_strings_outside_braces(query))
    if not blocks or not all(_block_has(block, required) for block in blocks):
        return QUERY_OUT_OF_SCOPE
    return None


def promql_scope_refusal(query: str, selector: str | None) -> str | None:
    """PromQL: every vector selector names the target's labels exactly, and no bare metric name selects others."""
    required = selector_matchers(selector)
    if not required:
        return None
    text = str(query or "")
    blocks = _BRACES.findall(text)
    if not blocks or not all(_block_has(block, required) for block in blocks):
        return QUERY_OUT_OF_SCOPE
    rest = _BRACES.sub("{}", text)
    rest = _STRING.sub(" ", rest)
    rest = re.sub(r"\[[^\[\]]*\]", " ", rest)
    rest = _GROUPING.sub(" ", rest)
    for match in _IDENTIFIER.finditer(rest):
        following = rest[match.end():].lstrip()
        # A name before "{" is a scoped selector's metric, before "(" a function; anything else selects a metric
        # without the target's labels.
        if following.startswith(("(", "{")) or match.group(1).lower() in _PROMQL_WORDS:
            continue
        return QUERY_OUT_OF_SCOPE
    return None


def _strip_strings_outside_braces(query: str) -> str:
    """LogQL line filters (``|= "x"``) are strings outside the stream selector: removed before finding selectors."""
    out, depth, index, text = [], 0, 0, str(query or "")
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and char in "\"'`":
            close = _string_end(text, index)
            out.append(" ")
            index = close + 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _string_end(text: str, start: int) -> int:
    quote, index = text[start], start + 1
    while index < len(text):
        if text[index] == "\\" and quote != "`":
            index += 2
            continue
        if text[index] == quote:
            return index
        index += 1
    return len(text)


__all__ = [
    "INVALID_WINDOW",
    "MAX_SPAN",
    "QUERY_OUT_OF_SCOPE",
    "WINDOW_OUT_OF_SCOPE",
    "AlertScope",
    "as_utc",
    "logql_scope_refusal",
    "parse_rfc3339",
    "promql_scope_refusal",
    "query_window",
    "rfc3339",
    "run_alert_scope",
    "scope_from",
    "selector_matchers",
]
