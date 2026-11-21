"""The seat proxy's minimal HTTP/1.1.

Reading a request, writing a response, and which headers cross to the platform, to ChatGPT and back to Codex.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

PROXY_TOKEN_HEADER = "X-Octryx-Seat-Proxy"

MAX_BODY_BYTES = 16 * 1024 * 1024

MAX_HEADER_LINES = 100

MAX_REPORT_HEAD = 2 * 1024 * 1024

MAX_REPORT_TAIL = 512 * 1024

# What Codex sends that ChatGPT needs (the platform's ``CODEX_SEAT_FORWARDED_HEADERS``).
UPSTREAM_HEADERS = ("authorization", "chatgpt-account-id", "openai-beta", "originator", "session_id", "session-id",
                    "thread-id", "version", "user-agent", "accept", "x-openai-subagent", "x-codex-turn-state")

# What the platform gets: the session's own headers and Codex's correlation ids; never the ChatGPT login.
PLATFORM_PREFIX = "x-octryx-"

PLATFORM_CONTEXT = ("session-id", "session_id", "thread-id", "x-openai-subagent")

RELAYED_RESPONSE = frozenset({"content-type", "retry-after", "x-request-id", "x-oai-request-id", "openai-model",
                              "x-openai-model", "x-reasoning-included"})

RELAYED_PREFIX = "x-codex-"

_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
            413: "Payload Too Large", 502: "Bad Gateway", 504: "Gateway Timeout"}

class _BadRequestError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason

@dataclass(slots=True)
class _Request:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

def error_body(status: int, state: str, reason: str, hint: str) -> bytes:
    """The platform's OpenAI-shaped error (``refusals.openai_error_response``) for the proxy's own refusals."""
    kind = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error",
            404: "not_found_error", 413: "invalid_request_error"}.get(status, "server_error")
    return json.dumps({"error": {"message": f"Octryx gateway: {state} ({reason}). {hint}", "type": kind,
                                 "param": None, "code": reason}}).encode()

async def _read_body(reader: asyncio.StreamReader, headers: Mapping[str, str]) -> bytes:
    if "chunked" in headers.get("transfer-encoding", "").lower():
        body = bytearray()
        while True:
            size = int((await reader.readline()).split(b";")[0].strip() or b"0", 16)
            if size == 0:
                await reader.readline()
                return bytes(body)
            if len(body) + size > MAX_BODY_BYTES:
                raise _BadRequestError(413, "request_body_too_large")
            body.extend(await reader.readexactly(size))
            await reader.readline()
    length = int(headers.get("content-length") or 0)
    if length > MAX_BODY_BYTES:
        raise _BadRequestError(413, "request_body_too_large")
    return await reader.readexactly(length) if length else b""

async def read_request(reader: asyncio.StreamReader) -> _Request | None:
    line = (await reader.readline()).decode("latin-1").strip()
    if not line:
        return None
    parts = line.split(" ")
    if len(parts) != 3:
        raise _BadRequestError(400, "request_invalid")
    headers: dict[str, str] = {}
    for _ in range(MAX_HEADER_LINES):
        raw = (await reader.readline()).decode("latin-1").rstrip("\r\n")
        if not raw:
            return _Request(parts[0], parts[1].split("?", 1)[0], headers, await _read_body(reader, headers))
        name, _, value = raw.partition(":")
        headers[name.strip().lower()] = value.strip()
    raise _BadRequestError(400, "request_invalid")

def _head(status: int, headers: Mapping[str, str], *, length: int | None = None) -> bytes:
    lines = [f"HTTP/1.1 {status} {_REASONS.get(status, 'Status')}", *(f"{k}: {v}" for k, v in headers.items()),
             f"content-length: {length}" if length is not None else "transfer-encoding: chunked", "connection: close"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")

async def write_whole(writer: asyncio.StreamWriter, status: int, body: bytes,
                      headers: Mapping[str, str] | None = None) -> None:
    writer.write(_head(status, {"content-type": "application/json", **(headers or {})}, length=len(body)) + body)
    await writer.drain()

async def write_error(writer: asyncio.StreamWriter, status: int, state: str, reason: str, hint: str) -> None:
    await write_whole(writer, status, error_body(status, state, reason, hint), {
        "x-octryx-gateway-state": state, "x-octryx-gateway-reason": reason})

def platform_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """The session's ``x-octryx-*`` headers and Codex's correlation ids: never the ChatGPT login, and never the
    proxy's own token, which shares the prefix but only proves the caller to this proxy."""
    return {name: value for name, value in headers.items()
            if (name.startswith(PLATFORM_PREFIX) or name in PLATFORM_CONTEXT) and value
            and name.lower() != PROXY_TOKEN_HEADER.lower()}

def upstream_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {name: headers[name] for name in UPSTREAM_HEADERS if headers.get(name)}

def relayed_headers(headers: httpx.Headers) -> dict[str, str]:
    return {name: value for name, value in headers.items()
            if name in RELAYED_RESPONSE or name.startswith(RELAYED_PREFIX)}

class AnswerCapture:
    """The answer for the report: its first :data:`MAX_REPORT_HEAD` bytes, then only a tail (``truncated``) so the
    final ``response.completed`` event (usage) still arrives. Both parts are cut at SSE event boundaries."""

    def __init__(self) -> None:
        self.head = bytearray()
        self.tail = bytearray()
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        room = MAX_REPORT_HEAD - len(self.head)
        if room > 0:
            self.head.extend(chunk[:room])
            chunk = chunk[room:]
        if chunk:
            self.truncated = True
            self.tail.extend(chunk)
            del self.tail[:-MAX_REPORT_TAIL]

    def raw(self) -> bytes:
        if not self.truncated:
            return bytes(self.head)
        end = self.head.rfind(b"\n\n")
        head = bytes(self.head[:end + 2]) if end >= 0 else b""
        start = self.tail.find(b"\n\n")
        return head + (bytes(self.tail[start + 2:]) if start >= 0 else b"")
