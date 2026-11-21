"""The proxy holds a call while the platform is briefly away and admits standalone search only in research."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from octryx_claude import codex_seat_proxy, seat_proxy_calls
from octryx_claude.codex_seat_proxy import SeatProxy
from tests.codex_seat_proxy_support import CHATGPT_TOKEN, STREAM, Fakes, _codex_headers, _post, _run


class _Unavailable(Fakes):
    """The platform answers 503 for the first ``admits`` admissions and ``reports`` reports."""

    def __init__(self, *, admits: int = 0, reports: int = 0, final_report: int = 200) -> None:
        super().__init__()
        self.admits, self.reports, self.final_report = admits, reports, final_report
        self.slept: list[float] = []

    def platform(self, request: httpx.Request) -> httpx.Response:
        request.read()
        if request.url.path == codex_seat_proxy.ADMIT_PATH:
            self.calls.append(("admit", request))
            if self.admits:
                self.admits -= 1
                return httpx.Response(503, text="no available server")
            return self.admit
        self.calls.append(("report", request))
        if self.reports:
            self.reports -= 1
            return httpx.Response(503, text="no available server")
        return httpx.Response(self.final_report, json={"recorded": True, "mismatch": []})

    def proxy(self, base_url: str = "https://platform.test") -> SeatProxy:
        async def sleep(seconds: float) -> None:
            self.slept.append(seconds)  # time passes only by sleeping: the retry budgets are exact

        return SeatProxy(base_url, platform_transport=httpx.MockTransport(self.platform),
                         upstream_transport=httpx.MockTransport(self.chatgpt), sleep=sleep,
                         clock=lambda: sum(self.slept))


def _run_and_settle(fakes: Fakes, call) -> Any:
    """:func:`_run`, then the background report retries finish (they outlive the proxy)."""
    async def scenario():
        proxy = await fakes.proxy().start()
        try:
            answer = await call(proxy)
        finally:
            await proxy.stop()
        while seat_proxy_calls._RETRYING:
            await asyncio.gather(*list(seat_proxy_calls._RETRYING))
        return answer

    return asyncio.run(scenario())


class _SearchFakes(Fakes):
    """The platform's search admit/report and ChatGPT's alpha/search (Codex's standalone web.run)."""

    def __init__(self, *, admit_status: int = 200) -> None:
        super().__init__()
        self.admit_status = admit_status

    def platform(self, request: httpx.Request) -> httpx.Response:
        request.read()
        if request.url.path == seat_proxy_calls.SEARCH_ADMIT_PATH:
            self.calls.append(("search-admit", request))
            if self.admit_status != 200:
                return httpx.Response(self.admit_status, json={"error": {"code": "seat_search_not_research_phase"}},
                                      headers={"x-octryx-state": "denied"})
            return httpx.Response(200, json={"ticket": "tc-1"})
        if request.url.path == seat_proxy_calls.SEARCH_REPORT_PATH:
            self.calls.append(("search-report", request))
            return httpx.Response(200, json={"recorded": True})
        return super().platform(request)

    def chatgpt(self, request: httpx.Request) -> httpx.Response:
        request.read()
        if request.url.path == seat_proxy_calls.UPSTREAM_SEARCH_PATH:
            self.calls.append(("upstream-search", request))
            return httpx.Response(200, json={"output": [{"type": "search_results", "results": [{"url": "https://sca.coffee"}]}]})
        return super().chatgpt(request)


def test_a_briefly_unavailable_platform_holds_the_call_instead_of_failing_it():
    """Minutes of 503 from the platform do not fail a turn whose Codex call has finished."""
    fakes = _Unavailable(admits=2, reports=3)
    answer = _run_and_settle(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))
    assert answer.status_code == 200 and answer.content == STREAM  # Codex never saw the 503
    assert [kind for kind, _ in fakes.calls] == ["admit"] * 3 + ["upstream"] + ["report"] * 4
    assert fakes.slept == [2.0, 4.0, 2.0, 4.0, 8.0]  # admit, then the report in the background
    assert len({request.content for request in fakes.named("report")}) == 1  # the same report each time


def test_a_refused_report_is_not_retried_and_a_lasting_outage_reaches_codex():
    fakes = _Unavailable(final_report=403)  # e.g. seat_ticket_used: a retry cannot change it
    _run_and_settle(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))
    assert [kind for kind, _ in fakes.calls] == ["admit", "upstream", "report"] and fakes.slept == []

    down = _Unavailable(admits=1000)
    answer = _run_and_settle(down, lambda proxy: _post(proxy, _codex_headers(proxy.token)))
    assert answer.status_code == 503 and not down.named("upstream")  # nothing sent to the model
    assert sum(down.slept) <= codex_seat_proxy.ADMIT_RETRY_SECONDS


def test_codex_standalone_search_is_admitted_sent_with_the_login_and_reported():
    fakes = _SearchFakes()
    search = {"commands": [{"type": "search", "query": "SCA brewing control chart"}], "model": "gpt-6.1-sol"}
    answer = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token), body=search, path="/alpha/search"))
    assert answer.status_code == 200 and "sca.coffee" in answer.text
    assert [kind for kind, _ in fakes.calls] == ["search-admit", "upstream-search", "search-report"]
    [admit] = fakes.named("search-admit")
    assert json.loads(admit.content) == search and "authorization" not in admit.headers  # never the ChatGPT login
    [upstream] = fakes.named("upstream-search")
    assert upstream.headers["authorization"] == f"Bearer {CHATGPT_TOKEN}"
    assert (upstream.url.host, upstream.url.path) == ("chatgpt.com", "/backend-api/codex/alpha/search")
    [report] = fakes.named("search-report")
    assert json.loads(report.content) == {"ticket": "tc-1", "status_code": 200}


def test_a_search_outside_a_research_phase_never_leaves_the_device():
    fakes = _SearchFakes(admit_status=403)
    search = {"commands": [{"type": "search", "query": "x"}]}
    answer = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token), body=search, path="/alpha/search"))
    assert answer.status_code == 403 and [kind for kind, _ in fakes.calls] == ["search-admit"]
