"""The Codex seat's loopback proxy (``seat_traffic: device``): the platform admits, the device sends.

The platform and ChatGPT are ``httpx.MockTransport`` fakes that record every request, so the order admit → upstream
→ report, the header split (ChatGPT login only upstream, session headers only to the platform) and "nothing sent"
on a refusal are checked exactly. Codex is played by an HTTP client on the loopback port.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import httpx

from octryx_claude import seat_proxy_http
from octryx_claude.seat_proxy_http import PROXY_TOKEN_HEADER, AnswerCapture
from tests.codex_seat_proxy_support import (
    ACCOUNT,
    ADMITTED,
    BODY,
    CHATGPT_TOKEN,
    STREAM,
    TICKET,
    Fakes,
    _codex_headers,
    _post,
    _run,
)


def test_a_call_is_admitted_sent_from_the_device_and_reported_in_that_order():
    fakes = Fakes()
    answer = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))

    assert answer.status_code == 200 and answer.content == STREAM  # byte for byte
    assert answer.headers["x-codex-primary-used-percent"] == "12.5"
    assert answer.headers["x-octryx-obligation"] == "masked-nothing"
    assert "set-cookie" not in answer.headers and "x-upstream-internal" not in answer.headers
    assert [kind for kind, _ in fakes.calls] == ["admit", "upstream", "report"]
    [admit] = fakes.named("admit")
    assert json.loads(admit.content) == BODY
    assert {"authorization", "chatgpt-account-id", "cookie", "x-codex-turn-metadata"}.isdisjoint(admit.headers)
    assert PROXY_TOKEN_HEADER.lower() not in admit.headers
    assert admit.headers["x-octryx-seat-credential"] == "seat-cred-123"
    assert admit.headers["session-id"] == "0199a1b2-c3d4"
    [upstream] = fakes.named("upstream")
    assert (upstream.url.scheme, upstream.url.host, upstream.url.path) == (
        "https", "chatgpt.com", "/backend-api/codex/responses")
    assert json.loads(upstream.content) == ADMITTED  # the admitted body, not Codex's own
    assert upstream.headers["authorization"] == f"Bearer {CHATGPT_TOKEN}"
    assert upstream.headers["chatgpt-account-id"] == ACCOUNT
    assert not [name for name in upstream.headers if name.startswith("x-octryx-")]
    assert {"cookie", "x-codex-turn-metadata", PROXY_TOKEN_HEADER.lower()}.isdisjoint(upstream.headers)
    report = fakes.report()
    assert (report["ticket"], report["body"], report["status_code"], report["complete"]) == (
        TICKET, ADMITTED, 200, True)
    assert base64.b64decode(report["response_b64"]) == STREAM and report["truncated"] is False
    assert report["headers"]["x-codex-primary-used-percent"] == "12.5" and "set-cookie" not in report["headers"]
    [sent] = fakes.named("report")
    assert "authorization" not in sent.headers and CHATGPT_TOKEN not in sent.content.decode()


def test_a_request_without_the_jobs_token_or_login_reaches_nobody():
    fakes = Fakes()

    async def calls(proxy):
        return [await _post(proxy, _codex_headers("not-the-token")),
                await _post(proxy, {k: v for k, v in _codex_headers(proxy.token).items() if k != PROXY_TOKEN_HEADER}),
                await _post(proxy, _codex_headers(proxy.token), path="/models"),
                await _post(proxy, {k: v for k, v in _codex_headers(proxy.token).items() if k != "authorization"})]

    wrong, missing, other_path, no_login = _run(fakes, calls)

    assert (wrong.status_code, missing.status_code, other_path.status_code) == (403, 403, 404)
    assert wrong.json()["error"]["code"] == "seat_proxy_token_invalid"
    assert (no_login.status_code, no_login.json()["error"]["code"]) == (401, "seat_subscription_login_missing")
    assert fakes.calls == []


def test_the_platforms_refusal_goes_back_to_codex_unchanged_and_nothing_is_sent():
    fakes = Fakes()
    refusal = {"error": {"message": "Octryx gateway: denied (secret_detected_in_prompt). Remove it.",
                         "type": "invalid_request_error", "param": None, "code": "secret_detected_in_prompt"}}
    fakes.admit = httpx.Response(400, json=refusal, headers={
        "x-octryx-gateway-state": "denied", "x-octryx-gateway-reason": "secret_detected_in_prompt"})

    answer = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))

    assert (answer.status_code, answer.json()) == (400, refusal)
    assert answer.headers["x-octryx-gateway-reason"] == "secret_detected_in_prompt"
    assert [kind for kind, _ in fakes.calls] == ["admit"]


def test_chatgpts_errors_are_relayed_unchanged_and_reported_and_unreachable_is_never_a_fallback():
    fakes = Fakes()
    error = {"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached"}}
    fakes.upstream = httpx.Response(429, json=error, headers={"retry-after": "60",
                                                              "x-codex-primary-used-percent": "100"})
    limited = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))

    assert (limited.status_code, limited.json(), limited.headers["retry-after"]) == (429, error, "60")
    assert fakes.report()["status_code"] == 429

    fakes = Fakes()
    fakes.upstream = httpx.ConnectError("no route")
    unreachable = _run(fakes, lambda proxy: _post(proxy, _codex_headers(proxy.token)))

    assert (unreachable.status_code, unreachable.json()["error"]["code"]) == (502, "upstream_unreachable")
    assert [kind for kind, _ in fakes.calls] == ["admit", "upstream", "report"]  # never the platform's relay route
    assert fakes.report()["status_code"] == 0


def test_the_proxy_listens_on_loopback_only_and_stops_with_the_job():
    fakes = Fakes()

    async def scenario():
        proxy = await fakes.proxy().start()
        host = proxy._server.sockets[0].getsockname()[0]
        port = proxy.port
        await proxy.stop()
        try:
            await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return host, "closed"
        return host, "open"

    assert asyncio.run(scenario()) == ("127.0.0.1", "closed")


def test_no_token_ticket_or_body_is_ever_logged(caplog):
    caplog.set_level(logging.DEBUG)
    fakes = Fakes()
    fakes.report_status = 500  # a failed report is logged by its status only
    tokens: list[str] = []

    async def call(proxy):
        tokens.append(proxy.token)
        return await _post(proxy, _codex_headers(proxy.token))

    assert _run(fakes, call).status_code == 200
    logged = caplog.text + " ".join(str(record.args) for record in caplog.records)
    assert "Codex seat report refused (status=500)" in caplog.text
    for secret in (CHATGPT_TOKEN, ACCOUNT, TICKET, tokens[0], "seat-cred-123", "Run the tests."):
        assert secret not in logged


def test_a_long_answer_is_reported_with_its_head_and_its_final_events():
    capture = AnswerCapture()
    event = b"event: response.output_text.delta\ndata: {\"delta\":\"" + b"x" * 1000 + b"\"}\n\n"
    for _ in range(3000):  # ~3 MB
        capture.add(event)
    capture.add(STREAM)

    raw = capture.raw()

    assert capture.truncated and raw.endswith(STREAM)
    assert len(raw) <= seat_proxy_http.MAX_REPORT_HEAD + seat_proxy_http.MAX_REPORT_TAIL
    assert all(part.startswith(b"event: ") for part in raw.split(b"\n\n") if part)  # cut at event boundaries
