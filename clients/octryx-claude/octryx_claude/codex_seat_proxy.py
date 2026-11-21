"""The Codex seat's loopback proxy: the platform admits, the device sends (``seat_traffic: device``).

When the platform's cluster cannot reach ``chatgpt.com``, a Codex seat turn through the gateway fails with
``504 upstream_timeout``. With the platform's switch on ``device`` (the default,
read from ``/client-policy``) a Codex seat session's provider is this proxy instead of the platform's seat route:

- it listens on **127.0.0.1 only**, on a random port, for one job (or one terminal session) and stops with it;
- every request must carry the job's random token (:data:`PROXY_TOKEN_HEADER`, from the process environment through
  Codex's ``env_http_headers``), so no other local process can use the person's login through it;
- for each ``POST /responses`` it asks the platform to **admit** the body (``/openai/seat/admit``, the seat route's
  own checks; a refusal goes back to Codex unchanged), sends the **admitted** body to exactly
  ``https://chatgpt.com/backend-api/codex/responses`` with the person's own ChatGPT login (Codex's ``Authorization``
  and ``chatgpt-account-id``, an allowlist of headers like the platform's), streams the answer back byte for byte, and
  then **reports** it (``/openai/seat/report``: the ticket, the admitted body, status, relayed headers and the raw
  answer, at most :data:`MAX_REPORT_HEAD` plus a tail) so the platform records it like a relayed call;
- the ChatGPT login goes only upstream, never to the platform; the upstream client has no environment proxies and no
  redirects (``trust_env=False``), like the platform's own; nothing of a token or a body is ever logged;
- an error is answered as it is (the platform's refusal, ChatGPT's error, or a fixed gateway-style error when a side
  cannot be reached); there is never a fallback to the platform's relay route.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import secrets
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx

from .seat_proxy_calls import (
    RETRY_FIRST_DELAY,
    RETRY_MAX_DELAY,
    RETRY_STATUSES,
    SeatProxyCalls,
    _Admitted,
    _Outcome,
)
from .seat_proxy_http import (
    PLATFORM_PREFIX,
    PROXY_TOKEN_HEADER,
    AnswerCapture,
    _BadRequestError,
    _head,
    _Request,
    platform_headers,
    read_request,
    relayed_headers,
    upstream_headers,
    write_error,
    write_whole,
)

logger = logging.getLogger(__name__)

PROXY_TOKEN_ENV = "OCTRYX_CODEX_SEAT_PROXY_TOKEN"  # not ``OCTRYX_*``: those are exported into the hook wrapper file
LISTEN_HOST = "127.0.0.1"
RESPONSES_PATH = "/responses"
ADMIT_PATH = "/api/v1/model-gateway/openai/seat/admit"
# Codex's standalone web search (``web.run``, Responses Lite models): ``POST <base_url>/alpha/search``.
SEARCH_PATH = "/alpha/search"
UPSTREAM_ORIGIN = "https://chatgpt.com"
UPSTREAM_PATH = "/backend-api/codex/responses"
STOP_GRACE_SECONDS = 10.0
# The platform briefly unavailable (for example minutes of 503 while its database pool is exhausted): an admission
# is retried for a while before Codex hears of it, a report until shortly before its ticket expires (15 minutes),
# in the background, past the end of the job.
ADMIT_RETRY_SECONDS = 180.0
HEADER_OBLIGATION = "x-octryx-obligation"


# --- HTTP/1.1 on the loopback socket (one request per connection) ------------------------------------------------


# --- what is sent where -----------------------------------------------------------------------------------------


class SeatProxy(SeatProxyCalls):
    """One job's proxy; :meth:`start` binds it, :meth:`stop` ends it (in-flight calls get a short grace to report)."""

    def __init__(self, platform_url: str, *, platform_transport: httpx.AsyncBaseTransport | None = None,
                 upstream_transport: httpx.AsyncBaseTransport | None = None, sleep: Any = None,
                 clock: Any = None) -> None:
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.monotonic
        self.token = secrets.token_urlsafe(32)
        self.port = 0
        self._platform_url = platform_url.rstrip("/")
        self._platform_transport = platform_transport
        self._upstream_transport = upstream_transport
        self._server: Any = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def url(self) -> str:
        return f"http://{LISTEN_HOST}:{self.port}"

    async def start(self) -> SeatProxy:
        self._server = await asyncio.start_server(self._accept, LISTEN_HOST, 0, limit=64 * 1024)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self, grace: float = STOP_GRACE_SECONDS) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            _done, late = await asyncio.wait(pending, timeout=grace)
            for task in late:
                task.cancel()
        with contextlib.suppress(Exception):
            await server.wait_closed()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            await self._serve(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if task is not None:
                self._tasks.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await read_request(reader)
        except (_BadRequestError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, _BadRequestError) else "request_invalid"
            await write_error(writer, getattr(exc, "status", 400), "denied", reason, "The request was not sent.")
            return
        if request is None:
            return
        offered = request.headers.get(PROXY_TOKEN_HEADER.lower(), "").encode("latin-1")
        if not hmac.compare_digest(offered, self.token.encode("ascii")):
            await write_error(writer, 403, "denied", "seat_proxy_token_invalid", "Not this job's Codex session.")
            return
        if request.method == "POST" and request.path == SEARCH_PATH:
            if not request.headers.get("authorization", "").strip():
                await write_error(writer, 401, "unauthorized", "seat_subscription_login_missing",
                                  "Sign in with your own ChatGPT account in this Codex profile: run codex login.")
                return
            await self._search(writer, request)
            return
        if request.method != "POST" or request.path != RESPONSES_PATH:
            await write_error(writer, 404, "denied", "seat_proxy_path_unknown", "Only Codex responses are sent.")
            return
        if not request.headers.get("authorization", "").strip():
            await write_error(writer, 401, "unauthorized", "seat_subscription_login_missing",
                              "Sign in with your own ChatGPT account in this Codex profile: run codex login.")
            return
        await self._call(writer, request)

    async def _call(self, writer: asyncio.StreamWriter, request: _Request) -> None:
        admitted = await self._admit(writer, request)
        if admitted is None:
            return
        started = time.monotonic()
        outcome = _Outcome(AnswerCapture())
        try:
            await self._relay(writer, request, admitted, outcome)
        finally:
            await self._report(request, admitted, outcome, duration_ms=int((time.monotonic() - started) * 1000))

    async def _admit(self, writer: asyncio.StreamWriter, request: _Request) -> _Admitted | None:
        """The platform's admission; its refusal goes back to Codex unchanged. An unavailable platform (502/503/504,
        a timeout, no connection) is asked again for :data:`ADMIT_RETRY_SECONDS` before Codex hears of it."""
        deadline, delay = self._clock() + ADMIT_RETRY_SECONDS, RETRY_FIRST_DELAY
        while True:
            answer, failure = await self._admit_once(request)
            unavailable = failure is not None or answer is None or answer.status_code in RETRY_STATUSES
            if not unavailable or self._clock() + delay > deadline:
                break
            logger.info("Codex seat admit retried (status=%s)", answer.status_code if answer is not None else failure)
            await self._sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)
        if failure == "timeout":
            await write_error(writer, 504, "gateway_timeout", "seat_admit_timeout", "The platform did not answer.")
            return None
        if failure is not None or answer is None:
            await write_error(writer, 502, "gateway_unreachable", "seat_admit_unreachable",
                              "The platform could not be reached; nothing was sent to the model.")
            return None
        if answer.status_code != 200:
            kept = {name: value for name, value in answer.headers.items()
                    if name.startswith(PLATFORM_PREFIX) or name == "retry-after"}
            await write_whole(writer, answer.status_code, answer.content, kept)
            return None
        try:
            parsed = answer.json()
            return _Admitted(str(parsed["ticket"]), dict(parsed["body"]), str(parsed.get("notice") or ""))
        except (ValueError, KeyError, TypeError):
            await write_error(writer, 502, "gateway_unreachable", "seat_admit_invalid", "The platform's answer was "
                              "not understood; nothing was sent to the model.")
            return None

    async def _admit_once(self, request: _Request) -> tuple[httpx.Response | None, str | None]:
        try:
            async with self._platform() as client:
                return await client.post(ADMIT_PATH, content=request.body, headers={
                    **platform_headers(request.headers), "content-type": "application/json"}), None
        except httpx.TimeoutException:
            return None, "timeout"
        except httpx.HTTPError:
            return None, "unreachable"

    async def _relay(self, writer: asyncio.StreamWriter, request: _Request, admitted: _Admitted,
                     outcome: _Outcome) -> None:
        """Admitted body to ChatGPT, the answer back to Codex as it comes (and into ``outcome``)."""
        async with self._upstream() as client:
            outgoing = client.build_request("POST", UPSTREAM_PATH, headers={
                **upstream_headers(request.headers), "content-type": "application/json"},
                content=json.dumps(admitted.body, ensure_ascii=False).encode("utf-8"))
            try:
                upstream = await client.send(outgoing, stream=True)
            except httpx.TimeoutException:
                await write_error(writer, 504, "gateway_timeout", "upstream_timeout", "ChatGPT did not answer.")
                return
            except httpx.HTTPError:
                await write_error(writer, 502, "gateway_unreachable", "upstream_unreachable",
                                  "ChatGPT could not be reached from this device.")
                return
            outcome.status, outcome.headers = upstream.status_code, relayed_headers(upstream.headers)
            shown = {**outcome.headers, **({HEADER_OBLIGATION: admitted.notice} if admitted.notice else {}),
                     "cache-control": "no-cache"}
            try:
                writer.write(_head(upstream.status_code, shown))
                outcome.complete = await self._stream(writer, upstream, outcome.capture)
            finally:
                await upstream.aclose()

    @staticmethod
    async def _stream(writer: asyncio.StreamWriter, upstream: httpx.Response, capture: AnswerCapture) -> bool:
        try:
            async for chunk in upstream.aiter_bytes():
                if not chunk:
                    continue  # an empty chunk would end the chunked answer early
                capture.add(chunk)
                writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                await writer.drain()
        except httpx.HTTPError:
            return False  # mid-stream the status is already sent; reported as incomplete
        except ConnectionError:
            return False  # Codex went away
        writer.write(b"0\r\n\r\n")
        with contextlib.suppress(ConnectionError):
            await writer.drain()
        return True

    def _platform(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._platform_url, transport=self._platform_transport,
                                 timeout=httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0))

    def _upstream(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=UPSTREAM_ORIGIN, transport=self._upstream_transport, trust_env=False,
                                 follow_redirects=False,
                                 timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0))


@contextlib.contextmanager
def running(platform_url: str) -> Iterator[SeatProxy]:
    """The proxy on a loop of its own thread, for the terminal session (``octryx codex``), stopped on exit."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="octryx-codex-seat-proxy", daemon=True)
    thread.start()
    proxy = SeatProxy(platform_url)
    try:
        asyncio.run_coroutine_threadsafe(proxy.start(), loop).result(10)
        yield proxy
    finally:
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(proxy.stop(), loop).result(STOP_GRACE_SECONDS + 5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


__all__ = [
    "ADMIT_PATH",
    "LISTEN_HOST",
    "PROXY_TOKEN_ENV",
    "UPSTREAM_ORIGIN",
    "UPSTREAM_PATH",
    "SeatProxy",
    "running",
]
