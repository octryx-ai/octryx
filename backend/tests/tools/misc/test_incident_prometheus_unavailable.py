"""A Prometheus that cannot answer is ``unavailable``, never ``{}``; under a scope the range runs over the alert window
and every selector must name the target's labels."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

import app.tools.prometheus as prometheus_module
from app.tools.alert_scope import AlertScope, promql_scope_refusal
from app.tools.context import ToolContext
from app.tools.prometheus import QueryPrometheus

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
SELECTOR = '{job="octryx-s5-canary"}'
SCOPE = AlertScope(target_id="octryx-s5-canary", metrics_selector=SELECTOR,
                   window_start=datetime(2026, 10, 15, 9, 30, tzinfo=UTC), window_end=None)
VECTOR = {"status": "success", "data": {"resultType": "vector", "result": [
    {"metric": {"job": "octryx-s5-canary"}, "value": [1, "0"]}]}}
MATRIX = {"status": "success", "data": {"resultType": "matrix", "result": [
    {"metric": {"job": "octryx-s5-canary"}, "values": [[1, "0"], [2, "0"]]}]}}


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                       project_config={"prometheus_url": "https://prom.example.test"})


@pytest.fixture
def prometheus(monkeypatch):
    calls: list[tuple[str, dict]] = []
    answers = {"/api/v1/query": httpx.Response(200, json=VECTOR), "/api/v1/query_range": httpx.Response(200, json=MATRIX)}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        answer = answers[request.url.path]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(prometheus_module, "utc_now_aware", lambda: NOW)

    def scoped(scope):
        async def run_alert_scope(_context):
            return scope
        monkeypatch.setattr(prometheus_module, "run_alert_scope", run_alert_scope)

    scoped(SCOPE)
    return calls, answers, scoped


async def _query(query: str = 'up{job="octryx-s5-canary"} == 0', **params) -> dict:
    return await QueryPrometheus().execute({"query": query, **params}, _context())


def _assert_unavailable(result: dict, code: str) -> None:
    assert result["error"] == code and result["code"] == code
    assert (result["evidence"]["status"], result["evidence"]["family"]) == ("unavailable", "metrics")
    assert result["evidence"]["target_id"] == "octryx-s5-canary" and result["evidence"]["reason"] == code
    assert "range_result" not in result and "instant_result" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/query", "/api/v1/query_range"])
async def test_a_500_is_unavailable_never_an_empty_result(prometheus, path):
    _calls, answers, _scoped = prometheus
    answers[path] = httpx.Response(500, text="internal error")
    _assert_unavailable(await _query(), "prometheus_http_500")


@pytest.mark.asyncio
async def test_a_timeout_and_a_connection_error_are_unavailable(prometheus):
    _calls, answers, _scoped = prometheus
    answers["/api/v1/query"] = httpx.ReadTimeout("timed out")
    _assert_unavailable(await _query(), "prometheus_unreachable: ReadTimeout")
    answers["/api/v1/query"] = httpx.ConnectError("refused")
    _assert_unavailable(await _query(), "prometheus_unreachable: ConnectError")


@pytest.mark.asyncio
async def test_status_error_and_a_non_json_answer_are_unavailable(prometheus):
    _calls, answers, _scoped = prometheus
    answers["/api/v1/query_range"] = httpx.Response(200, json={"status": "error", "errorType": "bad_data",
                                                                "error": "parse error"})
    _assert_unavailable(await _query(), "prometheus_status_bad_data")
    answers["/api/v1/query_range"] = httpx.Response(200, text="<html>proxy</html>")
    _assert_unavailable(await _query(), "prometheus_invalid_response")


@pytest.mark.asyncio
async def test_an_empty_vector_is_empty_and_data_is_ok_over_the_alert_window(prometheus):
    calls, answers, _scoped = prometheus
    ok = await _query()
    assert (ok["evidence"]["status"], ok["evidence"]["count"]) == ("ok", 1)
    assert next(iter(ok)) == "evidence"
    instant, ranged = calls[0][1], calls[1][1]
    assert instant["time"] == "2026-10-15T10:00:00Z"
    assert (ranged["start"], ranged["end"], ranged["step"]) == ("2026-10-15T09:30:00Z", "2026-10-15T10:00:00Z", "60")
    assert ok["evidence"]["window"] == {"start": "2026-10-15T09:30:00Z", "end": "2026-10-15T10:00:00Z"}
    empty = {"status": "success", "data": {"resultType": "vector", "result": []}}
    answers["/api/v1/query"] = httpx.Response(200, json=empty)
    answers["/api/v1/query_range"] = httpx.Response(200, json={"status": "success",
                                                                "data": {"resultType": "matrix", "result": []}})
    result = await _query()
    assert (result["evidence"]["status"], result["evidence"]["target_id"], result["evidence"]["count"]) == (
        "empty", "octryx-s5-canary", 0)
    assert result["range_result"] == {"resultType": "matrix", "result": []}


@pytest.mark.asyncio
async def test_without_a_scope_the_duration_still_works_and_start_end_are_honoured(prometheus):
    calls, _answers, scoped = prometheus
    scoped(None)
    result = await _query("up", duration="30m")
    assert calls[-1][1]["start"] == "2026-10-15T09:30:00Z" and result["evidence"]["target_id"] is None
    await _query("up", start="2026-10-15T06:00:00Z", end="2026-10-15T08:00:00Z")
    assert (calls[-1][1]["start"], calls[-1][1]["end"]) == ("2026-10-15T06:00:00Z", "2026-10-15T08:00:00Z")


@pytest.mark.asyncio
async def test_a_query_outside_the_target_is_refused_before_any_request(prometheus):
    calls, _answers, _scoped = prometheus
    for query in ("up", 'up{job="other"}', 'up{job=~"octryx-s5-canary|other"}', f"up{SELECTOR} / node_load1",
                  f"up{SELECTOR} or up{{}}"):
        result = await _query(query)
        assert (result["error"], result["evidence"]["status"]) == ("query_out_of_scope", "refused"), query
    assert calls == []
    for query in (f"sum by (instance) (rate(http_requests_total{SELECTOR}[5m])) > bool 0.5",
                  f'histogram_quantile(0.9, sum(rate(latency_bucket{SELECTOR}[5m])) by (le)) offset 5m',
                  f'label_replace(up{SELECTOR}, "a", "$1", "job", "(.*)") == 1e3'):
        assert promql_scope_refusal(query, SELECTOR) is None, query
