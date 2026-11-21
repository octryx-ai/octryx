"""``query_loki`` always sends a window; under an alert scope it is the alert's, and the target's labels.

- ``start``/``end`` reach Loki: the alert window by default (open end → the query time), the last hour without a
  scope; ``since`` narrows; the span is at most 24 h and ``limit`` at most 1000;
- under a scope an explicit window is clamped to the alert's; one wholly outside it, a selector without the target's
  labels or another value for them is refused before any request;
- an HTTP or transport error is ``unavailable`` with an ``error`` (no empty answer); no lines is a targeted ``empty``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

import app.tools.loki as loki_module
from app.tools.alert_scope import AlertScope, logql_scope_refusal
from app.tools.context import ToolContext
from app.tools.loki import QueryLoki

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
SCOPE = AlertScope(target_id="checkout", namespace="shop", logs_selector='{namespace="shop",app="checkout"}',
                   window_start=datetime(2026, 10, 15, 9, 15, tzinfo=UTC), window_end=None)
IN_SCOPE = '{namespace="shop", app="checkout"} |= "error"'


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                       project_config={"loki_url": "https://loki.example.test"})


@pytest.fixture
def loki(monkeypatch):
    calls: list[dict] = []
    answer = {"response": httpx.Response(200, json={"data": {"result": [
        {"stream": {"app": "checkout"}, "values": [["1", "boom"], ["2", "boom"]]}]}})}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        response = answer["response"]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(loki_module.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(loki_module, "utc_now_aware", lambda: NOW)

    def scoped(scope):
        async def run_alert_scope(_context):
            return scope
        monkeypatch.setattr(loki_module, "run_alert_scope", run_alert_scope)

    scoped(None)
    return calls, answer, scoped


async def _query(params: dict) -> dict:
    return await QueryLoki().execute(params, _context())


@pytest.mark.asyncio
async def test_the_default_window_is_the_alert_window_and_is_sent(loki):
    calls, _answer, scoped = loki
    scoped(SCOPE)
    result = await _query({"query": IN_SCOPE})
    assert (calls[0]["start"], calls[0]["end"]) == ("2026-10-15T09:15:00Z", "2026-10-15T10:00:00Z")
    assert calls[0]["limit"] == "100" and calls[0]["direction"] == "backward"
    assert next(iter(result)) == "evidence"
    assert result["evidence"] == {"v": 1, "family": "logs", "status": "ok", "target_id": "checkout",
                                  "namespace": "shop", "count": 2, "reason": "",
                                  "window": {"start": "2026-10-15T09:15:00Z", "end": "2026-10-15T10:00:00Z"}}


@pytest.mark.asyncio
async def test_without_a_scope_the_last_hour_since_and_the_caps(loki):
    calls, _answer, _scoped = loki
    await _query({"query": '{app="x"}'})
    assert (calls[-1]["start"], calls[-1]["end"]) == ("2026-10-15T09:00:00Z", "2026-10-15T10:00:00Z")
    await _query({"query": '{app="x"}', "since": "15m", "limit": 50000})
    assert (calls[-1]["start"], calls[-1]["limit"]) == ("2026-10-15T09:45:00Z", "1000")
    # A span over 24 h keeps the newest 24 h without a scope.
    result = await _query({"query": '{app="x"}', "start": "2026-10-10T00:00:00Z", "end": "2026-10-15T00:00:00Z"})
    assert (calls[-1]["start"], calls[-1]["end"]) == ("2026-10-14T00:00:00Z", "2026-10-15T00:00:00Z")
    assert result["evidence"]["target_id"] is None
    refused = await _query({"query": '{app="x"}', "since": "forever"})
    assert (refused["error"], refused["evidence"]["status"]) == ("invalid_window", "refused") and len(calls) == 3


@pytest.mark.asyncio
async def test_under_a_scope_the_window_is_clamped_and_capped_from_the_alert_onset(loki):
    calls, _answer, scoped = loki
    scoped(SCOPE)
    await _query({"query": IN_SCOPE, "start": "2026-10-15T08:00:00Z", "end": "2026-10-15T12:00:00Z"})
    assert (calls[-1]["start"], calls[-1]["end"]) == ("2026-10-15T09:15:00Z", "2026-10-15T10:00:00Z")
    long_alert = AlertScope(target_id="checkout", logs_selector=SCOPE.logs_selector,
                            window_start=NOW - timedelta(days=3), window_end=None)
    scoped(long_alert)
    await _query({"query": IN_SCOPE})
    assert (calls[-1]["start"], calls[-1]["end"]) == ("2026-10-12T10:00:00Z", "2026-10-13T10:00:00Z")
    scoped(SCOPE)
    before = await _query({"query": IN_SCOPE, "start": "2026-10-14T08:00:00Z", "end": "2026-10-14T09:00:00Z"})
    assert (before["error"], before["evidence"]["status"]) == ("window_out_of_scope", "refused")
    assert len(calls) == 2  # the refused query sent nothing


@pytest.mark.asyncio
async def test_a_selector_outside_the_target_is_refused_before_any_request(loki):
    calls, _answer, scoped = loki
    scoped(SCOPE)
    for query in ('{namespace="kube-system"}', '{namespace="shop"}', '{namespace=~"shop|kube-system",app="checkout"}',
                  IN_SCOPE + ' or {namespace="other",app="checkout"}', 'sum(rate({app="checkout"}[5m]))'):
        result = await _query({"query": query})
        assert (result["error"], result["evidence"]["status"]) == ("query_out_of_scope", "refused"), query
        assert result["evidence"]["reason"] == "query_out_of_scope"
    assert calls == []
    assert logql_scope_refusal('sum by (pod) (rate({app="checkout",namespace="shop"} |= "{x}" [5m]))',
                               SCOPE.logs_selector) is None


@pytest.mark.asyncio
async def test_an_http_or_transport_error_is_unavailable_and_no_lines_is_empty(loki):
    _calls, answer, scoped = loki
    scoped(SCOPE)
    answer["response"] = httpx.Response(502, text="bad gateway")
    failed = await _query({"query": IN_SCOPE})
    assert (failed["error"], failed["evidence"]["status"], failed["evidence"]["target_id"]) == (
        "loki_http_502", "unavailable", "checkout")
    assert "streams" not in failed
    answer["response"] = httpx.ConnectTimeout("timed out")
    timed_out = await _query({"query": IN_SCOPE})
    assert timed_out["evidence"]["status"] == "unavailable" and timed_out["code"] == "loki_unreachable"
    answer["response"] = httpx.Response(200, json={"data": {"result": []}})
    empty = await _query({"query": IN_SCOPE})
    assert (empty["total_lines"], empty["evidence"]["status"], empty["evidence"]["target_id"]) == (0, "empty",
                                                                                                    "checkout")


@pytest.mark.asyncio
async def test_no_loki_configured_is_unavailable():
    result = await QueryLoki().execute({"query": '{app="x"}'},
                                       ToolContext(user_id="u", project_ids=[], roles=[], session_id="s",
                                                   project_config={}))
    assert result["evidence"]["status"] == "unavailable" and "No Loki URL" in result["error"]
