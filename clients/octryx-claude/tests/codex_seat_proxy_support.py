"""Shared helpers for the test_codex_seat_proxy_* modules."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from octryx_claude import codex_seat_proxy
from octryx_claude.codex_seat_proxy import SeatProxy
from octryx_claude.seat_proxy_http import PROXY_TOKEN_HEADER

CHATGPT_TOKEN = ("eyJhb" + "GciOiJSUzI1NiJ9.") + "c" * 60 + ".sig"


ACCOUNT = "acct-0f1e2d3c"


TICKET = "tkt-" + "t" * 40


MODEL = "gpt-5-codex"


STREAM = (b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_1","model":"gpt-5-codex"}}'
          b'\n\nevent: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1",'
          b'"usage":{"input_tokens":10,"output_tokens":2}}}\n\n')


BODY = {"model": "gpt-5.5", "stream": True, "input": [{"type": "message", "role": "user",
                                                        "content": [{"type": "input_text", "text": "Run the tests."}]}]}


ADMITTED = {**BODY, "model": MODEL}  # the run's model guard mapped it down


class Fakes:
    """The platform (admit, report) and ChatGPT, recording what each received in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, httpx.Request]] = []
        self.admit = httpx.Response(200, json={"body": ADMITTED, "ticket": TICKET, "notice": "masked-nothing",
                                               "expires_in": 900})
        self.upstream: Any = httpx.Response(200, content=STREAM, headers={
            "content-type": "text/event-stream", "x-request-id": "req_1", "x-codex-primary-used-percent": "12.5",
            "set-cookie": "__cf_bm=drop", "x-upstream-internal": "drop"})
        self.report_status = 200

    def platform(self, request: httpx.Request) -> httpx.Response:
        request.read()
        if request.url.path == codex_seat_proxy.ADMIT_PATH:
            self.calls.append(("admit", request))
            return self.admit
        self.calls.append(("report", request))
        return httpx.Response(self.report_status, json={"recorded": True, "mismatch": []})

    def chatgpt(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(("upstream", request))
        if isinstance(self.upstream, Exception):
            raise self.upstream
        return self.upstream

    def proxy(self, base_url: str = "https://platform.test") -> SeatProxy:
        return SeatProxy(base_url, platform_transport=httpx.MockTransport(self.platform),
                         upstream_transport=httpx.MockTransport(self.chatgpt))

    def named(self, name: str) -> list[httpx.Request]:
        return [request for kind, request in self.calls if kind == name]

    def report(self) -> dict[str, Any]:
        [request] = self.named("report")
        return json.loads(request.content)


def _codex_headers(token: str, **extra: str) -> dict[str, str]:
    return {"authorization": f"Bearer {CHATGPT_TOKEN}", "chatgpt-account-id": ACCOUNT, "originator": "codex_cli_rs",
            "session-id": "0199a1b2-c3d4", "accept": "text/event-stream", "cookie": "a=b",
            "x-codex-turn-metadata": '{"workspace":"/Users/someone"}', "x-octryx-session": "k1",
            "x-octryx-workspace": "w1", "x-octryx-seat-credential": "seat-cred-123",
            PROXY_TOKEN_HEADER: token, **extra}


async def _post(proxy: SeatProxy, headers: dict[str, str], body: Any = None, path: str = "/responses"):
    async with httpx.AsyncClient(trust_env=False, timeout=10.0) as codex:
        return await codex.post(proxy.url + path, json=BODY if body is None else body, headers=headers)


def _run(fakes: Fakes, call) -> Any:
    async def scenario():
        proxy = await fakes.proxy().start()
        try:
            return await call(proxy)
        finally:
            await proxy.stop()

    return asyncio.run(scenario())
