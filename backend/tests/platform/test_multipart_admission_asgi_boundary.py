"""The multipart admission ASGI boundary, driven with hand-built scopes: bytes delivered downstream for oversized, streamed, malformed and within-limit bodies."""

from __future__ import annotations

import json

import pytest
from starlette.datastructures import Headers

from app.middleware.security.multipart_admission import (
    MALFORMED_FRAMING_DETAIL,
    MALFORMED_FRAMING_STATUS,
    TOO_LARGE_DETAIL,
    TOO_LARGE_STATUS,
    MultipartAdmissionMiddleware,
)
from app.multipart_admission_policy import (
    CONTENT_LENGTH_ABSENT,
    CONTENT_LENGTH_DECLARED,
    CONTENT_LENGTH_MALFORMED,
    DEFAULT_MULTIPART_REQUEST_BYTES,
    KNOWLEDGE_EVIDENCE_REQUEST_BYTES,
    declared_content_length,
)
from tests.support.multipart_admission_support import (
    BOUNDARY,
    CHUNK,
    LIMIT,
    MULTIPART_CONTENT_TYPE,
    OTHER_MULTIPART_PATH,
    OVERSIZE_CHUNKS,
    WORKSPACE_PATH,
    _part_header,
    _settings,
)


def _multipart_body(payload: bytes, *, field: str = "file", file_name: str = "runbook.txt") -> bytes:
    return _part_header(field=field, file_name=file_name) + payload + f"\r\n--{BOUNDARY}--\r\n".encode()


class _Downstream:
    def __init__(self, *, read_body: bool = True) -> None:
        self.read_body = read_body
        self.calls = 0
        self.receive_calls = 0
        self.body = b""

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        if self.read_body:
            while True:
                self.receive_calls += 1
                message = await receive()
                if message["type"] != "http.request":
                    break
                self.body += message.get("body") or b""
                if not message.get("more_body"):
                    break
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"accepted":true}'})


async def _drive(
    downstream: _Downstream,
    *,
    chunks: list[bytes],
    path: str = WORKSPACE_PATH,
    content_type: str = MULTIPART_CONTENT_TYPE,
    content_length: str | list[str] | None = "honest",
    limit: int = LIMIT,
) -> tuple[int, bytes]:
    headers = [(b"host", b"octryx.example"), (b"content-type", content_type.encode())]
    if content_length == "honest":
        headers.append((b"content-length", str(sum(len(chunk) for chunk in chunks)).encode()))
    elif isinstance(content_length, list):
        headers.extend((b"content-length", value.encode()) for value in content_length)
    elif content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    else:
        headers.append((b"transfer-encoding", b"chunked"))

    pending = list(chunks)

    async def receive():
        if not pending:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = pending.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    status = 0
    body = b""

    async def send(message):
        nonlocal status, body
        if message["type"] == "http.response.start":
            status = message["status"]
        else:
            body += message.get("body") or b""

    middleware = MultipartAdmissionMiddleware(downstream, settings=_settings(max_multipart_request_bytes=limit))
    await middleware(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("203.0.113.5", 44321),
            "server": ("octryx.example", 80),
        },
        receive,
        send,
    )
    return status, body


@pytest.mark.asyncio
async def test_a_declared_oversize_is_refused_without_reading_or_calling_downstream():
    downstream = _Downstream()
    status, body = await _drive(downstream, chunks=[_multipart_body(b"x" * (LIMIT * 2))])

    assert status == TOO_LARGE_STATUS
    assert TOO_LARGE_DETAIL in body.decode()
    assert (downstream.calls, downstream.receive_calls, downstream.body) == (0, 0, b"")


@pytest.mark.asyncio
async def test_a_streamed_body_without_content_length_is_bounded_by_raw_bytes():
    downstream = _Downstream()
    chunks = [_part_header()] + [b"x" * CHUNK] * OVERSIZE_CHUNKS
    status, _ = await _drive(downstream, chunks=chunks, content_length=None)

    assert status == TOO_LARGE_STATUS
    assert len(downstream.body) <= LIMIT
    assert sum(len(chunk) for chunk in chunks) > LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", ["10", "0", "000000010"])
async def test_a_dishonest_content_length_is_bounded_by_raw_bytes(declared):
    downstream = _Downstream()
    chunks = [b"x" * CHUNK] * OVERSIZE_CHUNKS
    status, body = await _drive(downstream, chunks=chunks, content_length=declared)

    assert status == TOO_LARGE_STATUS
    assert TOO_LARGE_DETAIL in body.decode()
    assert len(downstream.body) <= LIMIT


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([], (CONTENT_LENGTH_ABSENT, None)),
        (["512"], (CONTENT_LENGTH_DECLARED, 512)),
        ([" 512 "], (CONTENT_LENGTH_DECLARED, 512)),
        ([""], (CONTENT_LENGTH_MALFORMED, None)),
        (["-1"], (CONTENT_LENGTH_MALFORMED, None)),
        (["+512"], (CONTENT_LENGTH_MALFORMED, None)),
        (["not-a-number"], (CONTENT_LENGTH_MALFORMED, None)),
        (["512, 512"], (CONTENT_LENGTH_MALFORMED, None)),
        # ``str.isdigit`` is true for both of these; ``int()`` accepts only one.
        (["\u00b2"], (CONTENT_LENGTH_MALFORMED, None)),
        (["\u0665\u0661\u0662"], (CONTENT_LENGTH_MALFORMED, None)),
        (["512", "512"], (CONTENT_LENGTH_MALFORMED, None)),
        (["512", "1024"], (CONTENT_LENGTH_MALFORMED, None)),
    ],
)
def test_content_length_framing_is_read_as_an_explicit_state(raw, expected):
    assert declared_content_length(Headers(raw=[(b"content-length", v.encode()) for v in raw])) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "declared",
    ["", " ", "-1", "+512", "not-a-number", "512, 512", "\u00b2", ["512", "512"], ["512", "1024"]],
)
async def test_malformed_framing_is_refused_before_downstream_or_any_body_read(declared):
    downstream = _Downstream()
    chunks = [_multipart_body(b"y" * 32)]
    status, body = await _drive(downstream, chunks=chunks, content_length=declared)

    assert status == MALFORMED_FRAMING_STATUS
    assert json.loads(body) == {
        "error": MALFORMED_FRAMING_DETAIL,
        "detail": MALFORMED_FRAMING_DETAIL,
        "status_code": MALFORMED_FRAMING_STATUS,
        "request_id": None,
    }
    assert (downstream.calls, downstream.receive_calls, downstream.body) == (0, 0, b"")


@pytest.mark.asyncio
async def test_one_canonical_declaration_within_the_limit_is_still_accepted():
    payload = _multipart_body(b"y" * 256)
    downstream = _Downstream()
    status, body = await _drive(downstream, chunks=[payload], content_length=str(len(payload)))

    assert (status, body) == (200, b'{"accepted":true}')
    assert downstream.body == payload


@pytest.mark.asyncio
async def test_a_within_limit_multipart_request_passes_through_unchanged():
    payload = _multipart_body(b"y" * 512)
    downstream = _Downstream()
    status, body = await _drive(downstream, chunks=[payload[:100], payload[100:]])

    assert (status, body) == (200, b'{"accepted":true}')
    assert downstream.body == payload
    assert downstream.calls == 1


@pytest.mark.asyncio
async def test_a_non_multipart_request_is_not_touched_by_the_boundary():
    downstream = _Downstream()
    body_bytes = b'{"data":"' + b"z" * (LIMIT * 3) + b'"}'
    status, _ = await _drive(downstream, chunks=[body_bytes], content_type="application/json")

    assert status == 200
    assert downstream.body == body_bytes


@pytest.mark.asyncio
async def test_the_knowledge_route_limit_is_lower_than_the_global_ceiling():
    declared = str(KNOWLEDGE_EVIDENCE_REQUEST_BYTES + 1)
    global_ceiling = DEFAULT_MULTIPART_REQUEST_BYTES

    refused_downstream = _Downstream()
    refused, _ = await _drive(
        refused_downstream,
        chunks=[b""],
        path=WORKSPACE_PATH,
        content_length=declared,
        limit=global_ceiling,
    )

    accepted_downstream = _Downstream()
    accepted, _ = await _drive(
        accepted_downstream,
        chunks=[b""],
        path=OTHER_MULTIPART_PATH,
        content_length=declared,
        limit=global_ceiling,
    )

    assert (refused, refused_downstream.calls) == (TOO_LARGE_STATUS, 0)
    assert (accepted, accepted_downstream.calls) == (200, 1)


@pytest.mark.asyncio
async def test_the_boundary_ignores_non_http_scopes():
    seen: list[dict] = []

    async def echo(scope, receive, send):
        seen.append(scope)

    middleware = MultipartAdmissionMiddleware(echo, settings=_settings(max_multipart_request_bytes=LIMIT))
    for scope_type in ("websocket", "lifespan"):
        await middleware({"type": scope_type}, None, None)

    assert [scope["type"] for scope in seen] == ["websocket", "lifespan"]
